odoo.define('llm_experience/static/src/js/llm_tool_visibility.js', function (require) {
    'use strict';

    const Message = require('mail/static/src/components/message/message.js');
    const session = require('web.session');

    /**
     * Experiencia tipo ChatGPT para llamadas a herramientas.
     * Usuarios sin el grupo `llm_experience.group_llm_tool_debug` ven una
     * línea de estado en el mensaje del assistant y no el JSON técnico.
     */
    function _isLlmToolDebug() {
        try {
            return Boolean(session && session.llm_tool_debug);
        } catch (_e) {
            return false;
        }
    }

    if (typeof document !== 'undefined' && document.documentElement) {
        if (_isLlmToolDebug()) {
            document.documentElement.classList.add('o_llm_tool_debug');
        } else {
            document.documentElement.classList.add('o_llm_no_tool_debug');
        }
    }

    const _TOOL_LABEL_MAP = {
        odoo_record_retriever: {
            pending: 'Consultando registros en Odoo',
            done: 'Consultados registros en Odoo',
            error: 'No se pudo consultar registros en Odoo',
        },
        odoo_record_search: {
            pending: 'Buscando registros en Odoo',
            done: 'Búsqueda de registros completada',
            error: 'Falló la búsqueda de registros',
        },
        odoo_domain_search: {
            pending: 'Buscando registros en Odoo',
            done: 'Búsqueda de registros completada',
            error: 'Falló la búsqueda de registros',
        },
        odoo_record_creator: {
            pending: 'Creando / actualizando registros en Odoo',
            done: 'Registros creados / actualizados',
            error: 'No se pudieron crear / actualizar los registros',
        },
        odoo_record_updater: {
            pending: 'Actualizando registros en Odoo',
            done: 'Registros actualizados',
            error: 'No se pudieron actualizar los registros',
        },
        odoo_record_unlinker: {
            pending: 'Eliminando registros en Odoo',
            done: 'Registros eliminados',
            error: 'No se pudieron eliminar los registros',
        },
        odoo_record_writer: {
            pending: 'Actualizando registros en Odoo',
            done: 'Registros actualizados',
            error: 'No se pudieron actualizar los registros',
        },
        odoo_record_remover: {
            pending: 'Eliminando registros en Odoo',
            done: 'Registros eliminados',
            error: 'No se pudieron eliminar los registros',
        },
        odoo_model_info: {
            pending: 'Analizando la estructura del modelo',
            done: 'Estructura del modelo analizada',
            error: 'No se pudo analizar el modelo',
        },
        odoo_fields_info: {
            pending: 'Analizando campos del modelo',
            done: 'Campos analizados',
            error: 'No se pudieron analizar los campos',
        },
        odoo_model_inspector: {
            pending: 'Analizando la estructura del modelo',
            done: 'Estructura del modelo analizada',
            error: 'No se pudo analizar el modelo',
        },
        web_search: {
            pending: 'Buscando información en la web',
            done: 'Búsqueda web completada',
            error: 'Falló la búsqueda en la web',
        },
        web_search_20250305: {
            pending: 'Buscando información en la web',
            done: 'Búsqueda web completada',
            error: 'Falló la búsqueda en la web',
        },
        fetch_url: {
            pending: 'Consultando un enlace externo',
            done: 'Enlace externo consultado',
            error: 'No se pudo consultar el enlace',
        },
        llm_artifact_builder: {
            pending: 'Generando un artefacto',
            done: 'Artefacto generado',
            error: 'No se pudo generar el artefacto',
        },
        llm_mail_sender: {
            pending: 'Enviando correo',
            done: 'Correo enviado',
            error: 'No se pudo enviar el correo',
        },
        llm_task_status_reporter: {
            pending: 'Registrando el estado de la tarea',
            done: 'Estado de la tarea registrado',
            error: 'No se pudo registrar el estado de la tarea',
        },
    };

    function _prettifyToolName(rawName) {
        if (!rawName) {
            return '';
        }
        return String(rawName)
            .replace(/[_-]+/g, ' ')
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function _labelForStatus(rawName, status) {
        const key = (rawName || '').trim();
        const entry = key && _TOOL_LABEL_MAP[key];
        if (entry && entry[status]) {
            return entry[status];
        }
        const pretty = _prettifyToolName(key);
        if (status === 'done') {
            return pretty ? pretty + ': completado' : 'Acción completada';
        }
        if (status === 'error') {
            return pretty ? pretty + ': falló' : 'Acción con error';
        }
        return pretty ? 'Ejecutando ' + pretty.toLowerCase() : 'Odoo está trabajando';
    }

    function _threadMessages(msg) {
        const thread = msg && (msg.originThread || msg.thread);
        const raw = thread && thread.messages;
        if (!raw) {
            return [];
        }
        const arr = [];
        const len = raw.length || 0;
        for (let i = 0; i < len; i++) {
            arr.push(raw[i]);
        }
        return arr;
    }

    Object.defineProperty(Message.prototype, 'llmToolDebugEnabled', {
        get: function () {
            return _isLlmToolDebug();
        },
        configurable: true,
    });

    Object.defineProperty(Message.prototype, 'llmToolCallEntries', {
        get: function () {
            const msg = this.message;
            if (!msg || msg.llmRole !== 'assistant') {
                return [];
            }
            const calls = msg.toolCalls || [];
            if (!calls.length) {
                return [];
            }
            const resultsById = {};
            const threadMessages = _threadMessages(msg);
            for (let i = 0; i < threadMessages.length; i++) {
                const m = threadMessages[i];
                if (m && m.llmRole === 'tool' && m.toolCallId) {
                    resultsById[m.toolCallId] = m;
                }
            }
            return calls.map(function (call) {
                const callId = (call && call.id) || '';
                const rawName = (call && call.function && call.function.name) || '';
                const result = callId ? resultsById[callId] : null;
                let status = 'pending';
                if (result) {
                    status = result.toolCallResultIsError ? 'error' : 'done';
                }
                return {
                    id: callId || rawName || Math.random().toString(36).slice(2),
                    rawName: rawName,
                    status: status,
                    label: _labelForStatus(rawName, status),
                };
            });
        },
        configurable: true,
    });

    Message.prototype._llmExpApplyToolVisibility = function () {
        if (!this.el || !this.message) {
            return;
        }
        const isTool = this.message.llmRole === 'tool';
        this.el.classList.toggle('o_llm_tool_role_message', isTool);
        this.el.classList.toggle('d-none', isTool && !_isLlmToolDebug());
    };

    const _mounted = Message.prototype.mounted;
    Message.prototype.mounted = function () {
        if (_mounted) {
            _mounted.apply(this, arguments);
        }
        this._llmExpApplyToolVisibility();
    };

    const _patched = Message.prototype.patched;
    Message.prototype.patched = function () {
        if (_patched) {
            _patched.apply(this, arguments);
        }
        this._llmExpApplyToolVisibility();
    };

    return Message;
});
