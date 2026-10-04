# Plan: contexto, razonamiento y tokens (Gemini primero)

Alcance: `odooai16` (implementación de referencia) y port a `odooai14`.
Modelo principal en uso: `gemini-flash-latest` (hoy apunta a **Gemini 3.8 Flash**).

---

## 1. Diagnóstico

### 1.1 "El contexto se resetea" en chats largos o con muchos errores de tools

| # | Causa | Dónde |
|---|-------|-------|
| D1 | El historial que se envía al modelo es una **ventana fija de 25 mensajes** (`get_llm_messages(limit=25)`). Cada ronda de tools crea 2+ mensajes (assistant con `tool_calls` + uno `tool` por llamada). Con 6-10 llamadas fallidas, la pregunta original del usuario sale de la ventana y el modelo "olvida" de qué se hablaba. | `llm_assistant/models/llm_thread.py` |
| D2 | La ventana se corta por número de mensajes, no por turnos: puede empezar con un `function_response` huérfano o un `function_call` sin respuesta. Gemini los elimina/repara con respuestas sintéticas, lo que pierde más contexto. | `llm_gemini/models/gemini_provider.py` (`_gemini_strip_*`) |
| D3 | La compactación sólo se dispara al 92 % de **1 048 576 tokens**; con 25 mensajes nunca se alcanza, así que en la práctica no existe. Cuando corre, toma los **200 mensajes más antiguos** (orden asc + limit), no los recientes, y no mueve ningún "puntero": el historial enviado sigue siendo el mismo. | `llm_experience/models/llm_thread_usage.py` |
| D4 | Los resultados de tools no tienen tope de tamaño: un `search_read` grande se reenvía completo en cada ronda siguiente. | `llm_openai/models/mail_message.py`, `llm_experience/models/anthropic_provider.py` |
| D5 | No hay ninguna señal al modelo cuando repite la misma llamada fallida; entra en bucles de errores que llenan la ventana. | `llm_assistant/models/llm_thread.py` (`generate_messages`) |

### 1.2 Cálculo de tokens / coste

| # | Problema | Dónde |
|---|----------|-------|
| T1 | La estimación previa con `count_tokens` **siempre falla en silencio**: la Gemini API rechaza `system_instruction` en `count_tokens` (`ValueError: system_instruction parameter is not supported`). `usage_last_estimated_prompt` queda en 0. Además añade una llamada HTTP extra en cada ronda. | `llm_experience/models/gemini_provider.py` |
| T2 | Coste Gemini mal calculado: `promptTokenCount` **ya incluye** los tokens en caché, y se cobran otra vez como caché (doble conteo). Los tokens de razonamiento (`thoughtsTokenCount`) se facturan como salida y **no se suman**. | `_usage_apply_cost_line` |
| T3 | "Contexto vivo" = `max(estimación, total, prompt+salida)`; `total` incluye razonamiento, que no se reenvía → sobreestima. | `_usage_recompute_live_from_parts` |
| T4 | Sólo se acumula un total "facturable"; no hay totales separados de entrada / salida / razonamiento / caché ni nº de peticiones. | `llm_thread_usage.py` |
| T5 | En streaming con `include_thoughts`, las partes de pensamiento (`part.thought=True`) se emitirían como texto de respuesta. | `gemini_chat._consume_stream` |
| T6 | En streaming se guardaba como `gemini_content_json` sólo el `Content` del **último chunk**: se perdían texto, `function_call` y firmas de chunks anteriores, y al restaurar el historial había llamadas huérfanas que se eliminaban (más pérdida de contexto). | `gemini_chat._consume_stream` |
| T7 | `markdown2` convertía `campo_x_id` en `campo<em>x</em>id` y `html2plaintext` lo enviaba al modelo como `campo/x/id`: los nombres de campos y modelos de Odoo escritos por el usuario llegaban corruptos y provocaban consultas fallidas. | `llm_thread/models/llm_thread.py` (`_process_llm_body`) |
| T8 | Las líneas de coste se creaban sin `sudo()` y el grupo usuario sólo tiene lectura: para usuarios no administradores la línea de coste no se creaba (error silenciado). | `_usage_apply_cost_line` |

### 1.3 Selector de pensamiento

| # | Problema |
|---|----------|
| S1 | Mezcla dos ejes en un solo selector: *modo* (normal / investigación) y *esfuerzo de razonamiento* (pensamiento profundo). |
| S2 | "Respuesta normal" no envía `ThinkingConfig` → en 3.8 Flash usa el default (`medium`). No existe un modo realmente rápido. |
| S3 | "Pensamiento profundo" envía `thinking_budget=8192`, parámetro heredado de Gemini 2.5; Gemini 3.x usa `thinking_level`. El SDK instalado (google-genai 1.47) no expone `thinking_level`. |
| S4 | `openai_chat` no acepta `**kwargs` y el hilo le pasa `llm_thread` → `TypeError` con proveedores OpenAI. |

### 1.4 Capacidades verificadas contra la API (4-oct-2026)

| Modelo | `thinking_budget=0` | `minimal` | `low` / `medium` / `high` | budget + level juntos |
|--------|:---:|:---:|:---:|:---:|
| `gemini-flash-latest` → 3.8 Flash | ✅ (sin razonamiento) | ❌ 400 | ✅ | ❌ 400 |
| `gemini-3.1-pro-preview` | ❌ 400 "only works in thinking mode" | ❌ 400 | ✅ | ❌ 400 |

---

## 2. Diseño

### 2.1 Esfuerzo de razonamiento (como ChatGPT / Cursor / Claude)

Nuevo campo `llm.thread.reasoning_effort`: **Instantáneo · Bajo · Medio · Alto · Extra alto**.
El modo *Investigación profunda* pasa a ser un interruptor independiente (`chat_work_mode` = `normal` | `deep_research`).

Mapeo por proveedor (cadena de candidatos; si la API rechaza uno con 400 de thinking, se prueba el siguiente y se memoriza por modelo en el proceso):

| Esfuerzo | Gemini 3.x / `*-latest` | Gemini 2.5 (budget) | Anthropic (budget) | OpenAI razonadores |
|---|---|---|---|---|
| Instantáneo | `budget=0` → `minimal` → `low` (\*) | 0 (Pro: 128) | sin thinking | `minimal` |
| Bajo | `low` | 1 024 | sin thinking | `low` |
| Medio | `medium` | 4 096 | 4 096 | `medium` |
| Alto | `high` | 16 384 | 16 000 | `high` |
| Extra alto | `high` + instrucción de verificación exhaustiva | 24 576 / 32 768 | 32 000 | `high` |

(\*) Con `budget=0` Gemini 3.8 Flash a veces aún informa unas decenas de tokens de razonamiento: "Instantáneo" es razonamiento mínimo, no cero garantizado.

- `thinking_level` se envía con una subclase Pydantic de `ThinkingConfig` (mismo patrón que `ToolConfig` en el módulo) mientras el SDK no lo exponga.
- Valor por defecto del hilo: preferencia del usuario (último esfuerzo usado) → default del modelo (`llm.model.default_reasoning_effort`) → `medium`.
- Compatibilidad: escribir `chat_work_mode='deep_thinking'` (tareas programadas, código antiguo) se traduce a `reasoning_effort='high'`. Migración de datos existente.

### 2.2 Contexto estilo Cursor: nunca se pierde, se resume y continúa

Conceptos:

- **Presupuesto de contexto** (`llm.model.context_budget_tokens`, default 200 000; 0 = ventana completa del modelo). Es el "100 %" del medidor. 1M tokens por petición sería lento y caro; el presupuesto es configurable por modelo.
- **Puntero de corte** (`llm.thread.context_cutoff_message_id`): los mensajes con id ≤ corte ya están dentro del **resumen acumulado** (`usage_compaction_summary`) y no se reenvían.
- **Mensaje fijado**: el último mensaje del usuario siempre se envía, aunque quede antes del corte (compactación a mitad de un bucle de tools).

Flujo por ronda (`_generate_assistant_response`):

1. Construir historial = mensaje fijado + mensajes con id > corte (sin límite de cantidad).
2. Estimar tokens localmente (caracteres / *chars_per_token* calibrado con el uso real de la ronda anterior; sin llamada HTTP).
3. Si la estimación ≥ umbral de compactación (85 % del presupuesto) → **compactar** y reconstruir.
4. Enviar. Al recibir `usage_metadata`: actualizar contexto vivo (= prompt + salida de la última petición), totales, coste y calibración.
5. Si tras la respuesta el contexto vivo ≥ umbral → compactar antes de la siguiente ronda.

Compactación:

- Resumen **acumulativo**: resumen previo + transcripción de lo nuevo (usuario, respuestas, llamadas a tools con argumentos, resultados recortados, errores).
- Instrucciones del resumen: conservar objetivo del usuario, decisiones, IDs/registros encontrados, errores y lo aprendido de ellos (p. ej. "el campo X no existe en Y"), pasos pendientes.
- Transcripciones enormes se resumen por bloques (map-reduce) → nunca se descarta nada sin resumir.
- Si el modelo falla, resumen extractivo de respaldo (todas las peticiones del usuario + extractos de respuestas).
- El corte se coloca en un límite de ronda (antes de un mensaje `assistant`) para no romper pares `function_call` / `function_response`.
- Se publica una nota en el chat ("Contexto resumido: N mensajes, ~X → ~Y tokens") y el medidor vuelve a ~0 %.
- Acciones manuales en el widget: **Resumir ahora** y **Reiniciar contexto** (corte sin resumen).
- La llamada de resumen usa esfuerzo Instantáneo y su coste se registra en el hilo.

Sin límites de respuesta: no se corta el bucle de tools ni se fija `max_output_tokens`. Existe un parámetro de seguridad opcional `llm_experience.max_tool_rounds_per_turn` (default **0 = ilimitado**).

### 2.3 Resultados de tools y bucles de error

- Al formatear el historial, los resultados de tools de turnos anteriores se recortan (default 6 000 caracteres; errores 1 500) con una nota "[recortado: N caracteres; vuelve a consultar si necesitas el detalle]". Los del turno actual se mantienen hasta 60 000. El resultado completo sigue guardado en `body_json` (UI/auditoría). Parámetros ICP configurables.
- Detector de rachas: si las últimas ≥ 2 llamadas del turno fallaron, o se repite una llamada idéntica que ya falló, se añade una instrucción de sistema con los errores y la indicación de cambiar de estrategia (inspeccionar el modelo/campos, ajustar dominio, preguntar al usuario). No se detiene el proceso.

### 2.4 Tokens y coste correctos

- Uso normalizado: `prompt`, `cached`, `output`, `thoughts`, `tool_prompt`, `total`, `prompt_includes_cached`.
- Coste = (prompt − cached) × entrada + cached × caché + (output + thoughts) × salida (Gemini). Anthropic informa `prompt` sin caché (`prompt_includes_cached=False`).
- Totales del hilo: entrada, salida, razonamiento, caché, nº de peticiones; línea de coste con `thoughts_tokens`.
- Reintento automático con espera ante 429 / 500 / 503 (hasta 3 intentos, antes del primer chunk en streaming).

### 2.5 Widget en el compositor

```
[ ⚡ Medio ▾ ]  ( ◔ 23% )
```

- **Píldora de esfuerzo**: menú con los 5 niveles (descripción breve de cada uno) + interruptor *Investigación profunda*. Avisos por modelo (p. ej. "3.1 Pro no puede desactivar el razonamiento: Instantáneo usa Bajo").
- **Anillo de contexto** con % y color (verde / ámbar / rojo). Al pulsar, tarjeta con:
  - `46 k / 200 k tokens (23 %)` + barra con marca del umbral de resumen.
  - "Se resumirá al 85 % · faltan ~124 k tokens".
  - Última petición: entrada, caché, salida, razonamiento.
  - Conversación: totales, peticiones, coste USD, nº de resúmenes y fecha del último.
  - Botones **Resumir ahora** y **Reiniciar contexto**.
- Refresco por eventos del stream (sin el `setInterval` de 12 s que causaba parpadeo).

---

## 3. Fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Esfuerzo de razonamiento (campo, migración, mapeo Gemini con `thinking_level` + cadena de fallback, Anthropic, OpenAI), fix `openai_chat(**kwargs)`, partes `thought` fuera del texto | Implementado en esta entrega |
| 2 | Contexto sin pérdida: corte + mensaje fijado, estimación local calibrada, compactación acumulativa por bloques, acciones manuales | Implementado en esta entrega |
| 3 | Recorte de resultados de tools, detector de rachas de error, reintentos 429/5xx | Implementado en esta entrega |
| 4 | Tokens/coste correctos, totales por hilo, línea de coste con razonamiento | Implementado en esta entrega |
| 5 | Widget nuevo (v16 OWL 2 y v14 OWL 1) | Implementado en esta entrega |
| 6 | Port completo a `odooai14` | Implementado; validado sólo estáticamente (no hay servidor Odoo 14 en el entorno de desarrollo) |
| 7 (pendiente) | Mostrar resúmenes de pensamiento en vivo (`include_thoughts`) en un bloque plegable; caché explícita de Gemini (`cachedContents`) para system prompt + tools; uso/coste en OpenAI (`stream_options.include_usage`); actualizar `google-genai` en servidores para no depender de la subclase | Propuesto |

---

## 4. Configuración (ir.config_parameter)

| Clave | Default | Uso |
|---|---|---|
| `llm_experience.compaction_ratio` | `0.85` | Umbral de resumen sobre el presupuesto |
| `llm_experience.warning_ratio` | `0.70` | Color ámbar del medidor |
| `llm_experience.tool_result_max_chars_old` | `6000` | Recorte de resultados de turnos anteriores |
| `llm_experience.tool_result_max_chars_current` | `60000` | Recorte de resultados del turno actual |
| `llm_experience.tool_error_max_chars_old` | `1500` | Recorte de errores antiguos |
| `llm_experience.max_tool_rounds_per_turn` | `0` | 0 = ilimitado |
| `llm_experience.compaction_chunk_chars` | `240000` | Tamaño de bloque en resúmenes por partes |

Por modelo (`llm.model`): `context_window_tokens`, `context_budget_tokens`, `default_reasoning_effort`.

---

## 5. Pruebas

- Unitarias de mapeo esfuerzo → `ThinkingConfig` por familia de modelo y cadena de fallback.
- Ventana de historial: corte, mensaje fijado, límite de ronda.
- Compactación con proveedor simulado (sin red) y con fallo del modelo (resumen extractivo).
- Coste: caso con caché y razonamiento.
- Manual contra la API: 3.8 Flash con los 5 niveles; hilo con > 40 llamadas a tools fallidas → el modelo sigue recordando la petición original; resumen visible en el chat y medidor vuelve a ~0 %.

### Resultados de la prueba manual (4-oct-2026, copia de `vintest123`, `gemini-flash-latest` → 3.8 Flash)

| Comprobación | Resultado |
|---|---|
| Estimación local vs. `promptTokenCount` real | 6 171 vs. 6 274 (≈1,6 % tras calibrar) |
| Niveles Instantáneo / Bajo / Alto | `budget:0`, `level:low`, `level:high` aceptados por la API |
| Dos errores de tool seguidos (`campo inexistente`) | El modelo corrige la consulta y continúa |
| Presupuesto forzado a 9k tokens | Resumen automático en el turno 5 (14 mensajes, medidor 86 % → 67 %) |
| Memoria tras el resumen | Recuerda código de proyecto, presupuesto, error previo y precios de una lista anterior |
| Widget | Píldora de esfuerzo, tarjeta de contexto, Resumir ahora y Reiniciar contexto funcionando |

### Despliegue

1. Actualizar módulos: `llm_thread` (sólo Python, reiniciar), `llm_gemini`, `llm_openai`, `llm_assistant`, `llm_experience`, `llm_scheduled_task` (`-u`).
2. La migración de `llm_experience` convierte los hilos en "Pensamiento profundo" a esfuerzo **Alto** y descarta los resúmenes antiguos (se generaban sobre una ventana de 25 mensajes).
3. Revisar en cada modelo LLM el **Presupuesto de contexto** (default 200 000) y el **Esfuerzo por defecto** (default Medio).
4. Los hilos antiguos muy largos se resumirán automáticamente en su siguiente mensaje (una llamada extra al modelo, una sola vez).

---

## 6. Fase 2 — UI/UX de razonamiento, herramientas, popup y títulos (4-oct-2026)

### Diagnóstico

| # | Problema | Causa |
|---|----------|-------|
| U1 | El popup fallaba si el chat grande estaba abierto | Popup y chat grande compartían el singleton `messaging.llmChat` (una sola vista y un solo hilo activo). |
| U2 | El título del chat no se actualizaba en vivo (a veces ni al recargar) | 1) Cada mensaje trae `record_name` (el nombre del hilo **cuando se creó el mensaje**) y mail lo escribe sobre el título actual al cargar o recibir mensajes. 2) El cliente releía el hilo al recibir `done` antes de que la transacción se confirmara. |
| U3 | Consultas fallidas repetidas | El esquema de `domain` no permitía una lista como valor (`["name","in",[...]]`); Gemini partía el leaf y repetía la misma llamada inválida. |
| U4 | No se veía el razonamiento | Los resúmenes de pensamiento no se pedían ni se mostraban. |

### Cambios

- **Razonamiento en vivo**: Gemini (`include_thoughts`) y Anthropic emiten `thinking`; se muestra plegable («Pensando…» con el titular actual → «Pensó durante X s»). No se reenvía en el historial (sólo se conserva la firma). Parámetro `llm_experience.show_thinking` (default activo; nunca en «Instantáneo»).
- **Pasos de herramientas** estilo Cursor/ChatGPT: una línea por paso («Buscó en `product.template` · 3 resultados · 0,4 s»), plegable; detalle técnico sólo para el grupo de depuración (errores visibles para todos). En el popup los pasos se agrupan («Trabajó 17 s · 8 herramientas · 5 errores»).
- **Metadatos por respuesta**: esfuerzo · duración · tokens de entrada/salida/razonamiento (al pasar el ratón).
- **Medidor de contexto**: barra de composición (instrucciones, herramientas, resumen, conversación) y las notas de resumen se muestran como separadores.
- **Popup independiente** (`systray/llm_floating_dock.*`): pestañas múltiples, estado y stream propios, persistencia en `localStorage`, minimizar/ampliar, abrir en el chat completo, adjuntos, pegar archivos, detener generación. Convive con el chat grande.
- **Contexto de pantalla automático**: el popup envía la pantalla activa (modelo, registro, vista, migas, texto visible). La tool `odoo_active_screen` la lee bajo demanda cuando el usuario pregunta por «esto / este registro / esta pantalla»; sustituye al botón «Adjuntar HTML».
- **Títulos en vivo**: título provisional inmediato + título IA al terminar, evento SSE `thread_update` + bus `llm.thread/update`; `record_name` ya no pisa el título; commit antes de `done`.
- **Tools**: el dominio admite listas como valor, se reparan leafs partidos y el error de `model` ausente incluye un ejemplo completo.

### Verificación (v16, copia de `vintest123`)

- Popup sobre un formulario de contacto: el modelo llamó a `odoo_active_screen` y resumió el registro abierto.
- Popup + chat grande abiertos a la vez, dos pestañas en paralelo, sin errores de consola.
- Títulos actualizados en vivo en pestañas, barra lateral y cabecera; el hilo que mostraba «New Chat #91» muestra su título real.
- Consulta `["name", "in", [...]]` correcta a la primera tras el cambio de esquema.

### Odoo 14

Port completo (OWL 1, modelos `mail` de v14, POST form-urlencoded, adjuntos vía `ir.attachment`, contexto de pantalla desde la URL). **Validado sólo estáticamente**: no hay servidor Odoo 14 en el entorno.
