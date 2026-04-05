/** @odoo-module **/

import { Message } from "@mail/components/message/message";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

// ---------------------------------------------------------------------------
// CDN URLs para librerías de gráficos y PDF
// ---------------------------------------------------------------------------
const ECHARTS_CDN =
    "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js";
const JSPDF_CDN =
    "https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js";

/** Shortcodes estilo GitHub/Slack (:bar_chart:) → emoji (refuerzo en mensajes ya renderizados) */
const _LLM_EMOJI_SHORTCODE_MAP = {
    bar_chart: "📊",
    chart_with_upwards_trend: "📈",
    chart_with_downwards_trend: "📉",
    white_check_mark: "✅",
    x: "❌",
    heavy_check_mark: "✔️",
    warning: "⚠️",
    no_entry: "⛔",
    rocket: "🚀",
    fire: "🔥",
    bulb: "💡",
    memo: "📝",
    page_facing_up: "📄",
    email: "📧",
    incoming_envelope: "📨",
    package: "📦",
    moneybag: "💰",
    calendar: "📅",
    clock1: "🕐",
    hourglass_flowing_sand: "⏳",
    gear: "⚙️",
    wrench: "🔧",
    hammer: "🔨",
    pushpin: "📌",
    link: "🔗",
    mag: "🔍",
    eyes: "👀",
    thumbsup: "👍",
    thumbsdown: "👎",
    clap: "👏",
    pray: "🙏",
    smile: "😊",
    sweat_smile: "😅",
    thinking_face: "🤔",
    raised_hands: "🙌",
    tada: "🎉",
    zap: "⚡",
    star: "⭐",
    sparkles: "✨",
    question: "❓",
    exclamation: "❗",
    speech_balloon: "💬",
    robot_face: "🤖",
    computer: "💻",
    globe_with_meridians: "🌐",
    triangulation_flag: "🚩",
    dart: "🎯",
    bookmark: "🔖",
    books: "📚",
    green_circle: "🟢",
    red_circle: "🔴",
    yellow_circle: "🟡",
    large_blue_circle: "🔵",
    arrow_right: "➡️",
    arrow_left: "⬅️",
    arrow_up: "⬆️",
    arrow_down: "⬇️",
};

/**
 * Sustituye :shortcode: por emoji en nodos de texto (no dentro de code/pre).
 * @param {HTMLElement} bodyEl
 */
function _llmReplaceEmojiShortcodesInBody(bodyEl) {
    const walker = document.createTreeWalker(bodyEl, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            const p = node.parentElement;
            if (!p) {
                return NodeFilter.FILTER_REJECT;
            }
            if (p.closest("code, pre")) {
                return NodeFilter.FILTER_REJECT;
            }
            if (!node.nodeValue || node.nodeValue.indexOf(":") === -1) {
                return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    const nodes = [];
    while (walker.nextNode()) {
        nodes.push(walker.currentNode);
    }
    for (const node of nodes) {
        let v = node.nodeValue;
        const replaced = v.replace(/:([a-z0-9_+-]+):/gi, (m, name) => {
            const k = name.toLowerCase();
            return Object.prototype.hasOwnProperty.call(
                _LLM_EMOJI_SHORTCODE_MAP,
                k
            )
                ? _LLM_EMOJI_SHORTCODE_MAP[k]
                : m;
        });
        if (replaced !== v) {
            node.nodeValue = replaced;
        }
    }
}

// Promesas de carga (singleton por sesión de página)
let _echartsPromise = null;
let _jsPdfPromise = null;

/**
 * Carga una librería desde CDN (singleton para evitar cargas múltiples).
 * @param {string} url
 * @param {function} getter - función que devuelve el global si ya está cargado
 * @param {function} resolveWith - función que devuelve el valor para resolver
 * @returns {Promise}
 */
function _loadScript(url, getter, resolveWith) {
    return new Promise((resolve, reject) => {
        const already = getter();
        if (already) {
            resolve(resolveWith());
            return;
        }
        const s = document.createElement("script");
        s.src = url;
        s.crossOrigin = "anonymous";
        s.onload = () => resolve(resolveWith());
        s.onerror = () =>
            reject(new Error(`[LLM Charts] No se pudo cargar: ${url}`));
        document.head.appendChild(s);
    });
}

function loadECharts() {
    if (!_echartsPromise) {
        _echartsPromise = _loadScript(
            ECHARTS_CDN,
            () => window.echarts,
            () => window.echarts
        ).catch((e) => {
            _echartsPromise = null;
            throw e;
        });
    }
    return _echartsPromise;
}

function loadJsPDF() {
    if (!_jsPdfPromise) {
        _jsPdfPromise = _loadScript(
            JSPDF_CDN,
            () => window.jspdf,
            () => window.jspdf
        ).catch((e) => {
            _jsPdfPromise = null;
            throw e;
        });
    }
    return _jsPdfPromise;
}

// ---------------------------------------------------------------------------
// Patch del componente Message
// ---------------------------------------------------------------------------
patch(Message.prototype, "llm_thread.MessageUX", {
    setup() {
        this._super();
        this.notification = useService("notification");
        this.actionService = useService("action");
    },

    /** @param {string} text */
    async copyLlmTextToClipboard(text) {
        const t = text || "";
        try {
            await navigator.clipboard.writeText(t);
            this.notification.add("Copiado al portapapeles", { type: "success" });
        } catch (e) {
            this.notification.add("No se pudo copiar", { type: "danger" });
        }
    },

    _update() {
        this._super(...arguments);
        if (this._contentRef?.el) {
            this._llmEnhanceAssistantDom(this._contentRef.el);
        }
    },

    /**
     * Enhances assistant message DOM: tables, images, ECharts blocks.
     * @param {HTMLElement} contentEl
     */
    _llmEnhanceAssistantDom(contentEl) {
        const bodies = contentEl.querySelectorAll(".o_Message_prettyBody");
        for (const body of bodies) {
            _llmReplaceEmojiShortcodesInBody(body);
            // --- Tablas con botón "Copiar" ---
            for (const table of body.querySelectorAll(
                "table:not(.o_llm_table_enhanced)"
            )) {
                table.classList.add("o_llm_table_enhanced");
                const wrap = document.createElement("div");
                wrap.className = "o_llm_table_wrap my-2";
                table.parentNode.insertBefore(wrap, table);
                wrap.appendChild(table);
                const bar = document.createElement("div");
                bar.className = "d-flex justify-content-end mb-1";
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "btn btn-sm btn-outline-secondary";
                btn.innerHTML =
                    '<i class="fa fa-copy me-1" aria-hidden="true"></i>Copiar tabla';
                btn.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const text = this._llmTableToTsv(table);
                    navigator.clipboard.writeText(text).then(
                        () =>
                            this.notification.add("Tabla copiada", {
                                type: "success",
                            }),
                        () =>
                            this.notification.add("No se pudo copiar", {
                                type: "danger",
                            })
                    );
                });
                bar.appendChild(btn);
                wrap.insertBefore(bar, table);
            }

            // --- Imágenes responsivas ---
            for (const img of body.querySelectorAll(
                "img:not(.o_llm_img_enhanced)"
            )) {
                img.classList.add("o_llm_img_enhanced", "rounded", "border");
                img.style.maxWidth = "100%";
                img.style.height = "auto";
            }

            // --- Bloques ECharts ---
            this._llmRenderEChartsBlocks(body);
        }
    },

    // -----------------------------------------------------------------------
    // ECharts rendering
    // -----------------------------------------------------------------------

    /**
     * Detecta divs .o_llm_echarts_raw (generados por _process_llm_body en Python)
     * y los reemplaza con gráficos interactivos ECharts.
     *
     * NOTA: markdown2 no preserva el nombre del lenguaje en bloques de código,
     * por eso usamos un <div> con el JSON en el texto como protocolo de transporte.
     * textContent del div decodifica automáticamente las entidades HTML (&quot; → ", etc.)
     *
     * @param {HTMLElement} bodyEl
     */
    _llmRenderEChartsBlocks(bodyEl) {
        const echartsDivs = bodyEl.querySelectorAll(
            "div.o_llm_echarts_raw:not(.o_llm_echarts_rendered)"
        );
        for (const div of echartsDivs) {
            div.classList.add("o_llm_echarts_rendered");

            // textContent decodifica entidades HTML automáticamente (&quot; → ", etc.)
            const optionStr = (div.textContent || "").trim();
            let option;
            try {
                option = JSON.parse(optionStr);
            } catch (e) {
                console.warn("[LLM Charts] JSON ECharts inválido:", e.message, optionStr.slice(0, 200));
                continue;
            }

            // Extraer metadata de drill-down (campo personalizado ignorado por ECharts)
            const odooLinks = option.odoo_links || null;

            // Construir el wrapper del gráfico y reemplazar el div contenedor
            const wrapper = this._llmBuildChartWrapper(option, odooLinks);
            div.parentNode.replaceChild(wrapper, div);

            // Inicializar ECharts de forma asíncrona
            this._llmInitChart(wrapper, option, odooLinks);
        }
    },

    /**
     * Crea el DOM del contenedor del gráfico con la barra de acciones.
     */
    _llmBuildChartWrapper(option, odooLinks) {
        const title =
            (option.title?.text || option.title?.[0]?.text || "Gráfico")
                .toString()
                .slice(0, 80);

        const wrapper = document.createElement("div");
        wrapper.className = "o_llm_echarts_wrapper";

        // Barra de acciones
        const actions = document.createElement("div");
        actions.className = "o_llm_echarts_actions";
        actions.innerHTML = `
            <span class="o_llm_echarts_title text-muted small me-auto"
                  style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%">
                <i class="fa fa-bar-chart me-1" aria-hidden="true"></i>${_escape(title)}
            </span>
            ${
                odooLinks
                    ? `<button class="btn btn-sm btn-outline-primary o_llm_chart_odoo_btn" title="${_escape(odooLinks.label || "Ver en Odoo")}">
                    <i class="fa fa-external-link me-1"></i>${_escape(odooLinks.label || "Ver en Odoo")}
                </button>`
                    : ""
            }
            <button class="btn btn-sm btn-outline-secondary o_llm_chart_pdf_btn" title="Descargar PDF">
                <i class="fa fa-file-pdf-o me-1"></i>PDF
            </button>
            <button class="btn btn-sm btn-outline-secondary o_llm_chart_png_btn" title="Descargar imagen">
                <i class="fa fa-download me-1"></i>PNG
            </button>
        `;

        // Área del gráfico con estado de carga
        const canvas = document.createElement("div");
        canvas.className = "o_llm_echarts_canvas";
        canvas.innerHTML = `
            <div class="o_llm_echarts_loading">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                <span>Cargando gráfico…</span>
            </div>
        `;

        wrapper.appendChild(actions);
        wrapper.appendChild(canvas);
        return wrapper;
    },

    /**
     * Carga ECharts y renderiza el gráfico en el wrapper.
     */
    async _llmInitChart(wrapper, option, odooLinks) {
        const canvas = wrapper.querySelector(".o_llm_echarts_canvas");
        try {
            const echarts = await loadECharts();
            if (!echarts) throw new Error("ECharts no disponible");

            // Limpiar el spinner
            canvas.innerHTML = "";

            const chart = echarts.init(canvas, null, { renderer: "canvas" });
            chart.setOption(option);

            // Responsive
            const resizeObserver = new ResizeObserver(() => {
                try { chart.resize(); } catch (_) {}
            });
            resizeObserver.observe(canvas);

            // Limpieza al desmontar
            wrapper._echartsInstance = chart;
            wrapper._echartsObserver = resizeObserver;

            // --- Botón PNG (descarga nativa de ECharts) ---
            const pngBtn = wrapper.querySelector(".o_llm_chart_png_btn");
            if (pngBtn) {
                pngBtn.addEventListener("click", () => {
                    const dataUrl = chart.getDataURL({
                        type: "png",
                        pixelRatio: 2,
                        backgroundColor: "#fff",
                    });
                    const link = document.createElement("a");
                    const chartTitle =
                        option.title?.text || option.title?.[0]?.text || "grafico";
                    link.download = `${_sanitizeFilename(chartTitle)}.png`;
                    link.href = dataUrl;
                    link.click();
                });
            }

            // --- Botón PDF ---
            const pdfBtn = wrapper.querySelector(".o_llm_chart_pdf_btn");
            if (pdfBtn) {
                pdfBtn.addEventListener("click", () => {
                    this._llmDownloadChartPdf(chart, option, wrapper);
                });
            }

            // --- Drill-down Odoo ---
            if (odooLinks) {
                const odooBtn = wrapper.querySelector(".o_llm_chart_odoo_btn");
                if (odooBtn) {
                    odooBtn.addEventListener("click", () => {
                        this._llmOpenOdooRecords(odooLinks, null);
                    });
                }
                chart.on("click", (params) => {
                    this._llmHandleChartClick(params, odooLinks);
                });
                // Visual hint that the chart is clickable
                canvas.style.cursor = "pointer";
                canvas.title = odooLinks.label || "Clic para ver registros en Odoo";
            }
        } catch (e) {
            console.error("[LLM Charts] Error al inicializar ECharts:", e);
            canvas.innerHTML = `
                <div class="o_llm_echarts_error text-danger p-3">
                    <i class="fa fa-exclamation-circle me-1"></i>
                    No se pudo cargar el gráfico. Verifica la conexión a internet
                    (se necesita CDN para ECharts).
                </div>
            `;
        }
    },

    // -----------------------------------------------------------------------
    // PDF export
    // -----------------------------------------------------------------------

    /**
     * Exporta el gráfico + texto explicativo a PDF usando jsPDF.
     */
    async _llmDownloadChartPdf(chart, option, wrapper) {
        try {
            const jsPdfLib = await loadJsPDF();
            if (!jsPdfLib?.jsPDF) throw new Error("jsPDF no disponible");
            const { jsPDF } = jsPdfLib;

            const chartTitle =
                option.title?.text || option.title?.[0]?.text || "Gráfico";

            // Capturar imagen del gráfico (alta resolución)
            const imgData = chart.getDataURL({
                type: "png",
                pixelRatio: 2,
                backgroundColor: "#ffffff",
            });

            const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
            const pageW = doc.internal.pageSize.getWidth();
            const pageH = doc.internal.pageSize.getHeight();
            const margin = 15;

            // --- Encabezado ---
            doc.setFontSize(18);
            doc.setTextColor(40, 40, 40);
            doc.text(chartTitle, margin, margin + 5);

            // Línea separadora
            doc.setDrawColor(180, 180, 180);
            doc.line(margin, margin + 9, pageW - margin, margin + 9);

            // --- Imagen del gráfico ---
            const imgW = pageW - margin * 2;
            const imgH = imgW * (9 / 16); // relación 16:9
            const imgY = margin + 14;
            doc.addImage(imgData, "PNG", margin, imgY, imgW, imgH);

            // --- Texto explicativo (párrafos después del gráfico) ---
            const bodyEl = wrapper.closest(".o_Message_prettyBody");
            let explanation = "";
            if (bodyEl) {
                // Recolectar texto de todos los nodos de texto del body,
                // excluyendo el propio wrapper del gráfico
                const clone = bodyEl.cloneNode(true);
                clone.querySelectorAll(".o_llm_echarts_wrapper").forEach((el) =>
                    el.remove()
                );
                clone.querySelectorAll(
                    "table,pre,code,script,style"
                ).forEach((el) => el.remove());
                explanation = (clone.textContent || "").trim().replace(/\s+/g, " ");
            }

            if (explanation) {
                const textY = imgY + imgH + 10;
                doc.setFontSize(10);
                doc.setTextColor(80, 80, 80);
                const lines = doc.splitTextToSize(explanation, pageW - margin * 2);
                // Paginación si el texto es muy largo
                let currentY = textY;
                for (const line of lines) {
                    if (currentY > pageH - margin) {
                        doc.addPage();
                        currentY = margin;
                    }
                    doc.text(line, margin, currentY);
                    currentY += 5;
                }
            }

            // --- Pie de página ---
            const dateStr = new Date().toLocaleDateString("es-ES", {
                day: "2-digit",
                month: "long",
                year: "numeric",
            });
            doc.setFontSize(8);
            doc.setTextColor(150, 150, 150);
            doc.text(
                `Generado el ${dateStr} · Odoo AI Chat`,
                margin,
                pageH - 6
            );

            doc.save(`${_sanitizeFilename(chartTitle)}.pdf`);
        } catch (e) {
            console.error("[LLM Charts] Error al generar PDF:", e);
            this.notification.add(
                "No se pudo generar el PDF. Verifica la conexión a internet.",
                { type: "danger" }
            );
        }
    },

    // -----------------------------------------------------------------------
    // Drill-down a registros Odoo
    // -----------------------------------------------------------------------

    /**
     * Maneja el clic en un elemento del gráfico y abre registros Odoo.
     */
    _llmHandleChartClick(params, odooLinks) {
        const name = params.name || params.seriesName || "";
        const value = params.value !== undefined ? params.value : "";
        this._llmOpenOdooRecords(odooLinks, { name, value, params });
    },

    /**
     * Navega a la vista lista de Odoo aplicando el dominio del drill-down.
     */
    _llmOpenOdooRecords(odooLinks, context) {
        if (!odooLinks?.model) return;

        let domain = [];
        if (odooLinks.domain_template && context?.name) {
            try {
                const domStr = odooLinks.domain_template.replace(
                    /\{\{name\}\}/g,
                    JSON.stringify(context.name)
                );
                domain = JSON.parse(domStr);
            } catch (e) {
                console.warn("[LLM Charts] Dominio de drill-down inválido:", e);
            }
        }

        const actionName = context?.name
            ? `${odooLinks.label || odooLinks.model}: ${context.name}`
            : odooLinks.label || odooLinks.model;

        try {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                name: actionName,
                res_model: odooLinks.model,
                views: [
                    [false, "list"],
                    [false, "form"],
                ],
                domain,
                target: "current",
            });
        } catch (e) {
            console.error("[LLM Charts] Error al abrir vista Odoo:", e);
            this.notification.add(
                "No se pudo abrir la vista de Odoo.",
                { type: "warning" }
            );
        }
    },

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    _llmTableToTsv(table) {
        const rows = [...table.querySelectorAll("tr")];
        return rows
            .map((tr) =>
                [...tr.querySelectorAll("th,td")]
                    .map((c) => (c.textContent || "").trim().replace(/\t/g, " "))
                    .join("\t")
            )
            .join("\n");
    },
});

// ---------------------------------------------------------------------------
// Funciones utilitarias (fuera del patch para evitar 'this' context issues)
// ---------------------------------------------------------------------------

function _escape(str) {
    return (str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function _sanitizeFilename(str) {
    return (str || "grafico")
        .replace(/[^a-zA-Z0-9\u00C0-\u024F\s_-]/g, "_")
        .replace(/\s+/g, "_")
        .slice(0, 60);
}
