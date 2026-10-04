odoo.define('llm_thread/static/src/js/llm_ui_utils.js', function (require) {
    'use strict';

    /**
     * Utilidades de presentación compartidas por el chat grande y el chat
     * flotante: etiquetas legibles de herramientas, duraciones, tokens y
     * razonamiento.
     */

    var EFFORT_LABELS = {
        instant: 'Instantáneo',
        low: 'Bajo',
        medium: 'Medio',
        high: 'Alto',
        xhigh: 'Extra alto',
    };

    /** Componentes opcionales que otros módulos registran (p. ej. el medidor). */
    var extraComponents = {};

    function parseToolArgs(raw) {
        if (!raw) {
            return {};
        }
        if (typeof raw === 'object') {
            return raw;
        }
        try {
            return JSON.parse(raw) || {};
        } catch (e) {
            return {};
        }
    }

    function humanize(name) {
        var text = String(name || 'herramienta').replace(/[_.]+/g, ' ').trim();
        return text.charAt(0).toUpperCase() + text.slice(1);
    }

    function hostOf(url) {
        try {
            return new URL(url).host;
        } catch (e) {
            return url || '';
        }
    }

    function countResult(result) {
        if (Array.isArray(result)) {
            return result.length;
        }
        if (result && typeof result === 'object') {
            var keys = ['rows', 'records', 'registros', 'result'];
            for (var i = 0; i < keys.length; i++) {
                if (Array.isArray(result[keys[i]])) {
                    return result[keys[i]].length;
                }
            }
        }
        return null;
    }

    /**
     * Describe un paso de herramienta: verbo en presente mientras corre y en
     * pasado al terminar (como Cursor / ChatGPT).
     */
    function describeToolStep(name, rawArgs, status, result) {
        var args = parseToolArgs(rawArgs);
        var done = status === 'completed' || status === 'error';
        var model = args.model || '';
        function pick(running, finished) {
            return done ? finished : running;
        }
        var label;
        var target = '';
        var icon = 'fa-wrench';
        switch (name) {
            case 'odoo_record_retriever':
                icon = 'fa-search';
                if (args.mode === 'sql') {
                    label = pick('Consultando con SQL', 'Consultó con SQL');
                } else {
                    label = pick('Buscando en', 'Buscó en');
                    target = model;
                }
                break;
            case 'odoo_model_inspector':
                icon = 'fa-sitemap';
                label = pick('Inspeccionando', 'Inspeccionó');
                target = model || args.model_name || '';
                break;
            case 'odoo_record_creator':
                icon = 'fa-plus-circle';
                label = pick('Creando en', 'Creó en');
                target = model;
                break;
            case 'odoo_record_updater':
                icon = 'fa-pencil';
                label = pick('Actualizando', 'Actualizó');
                target = model;
                break;
            case 'odoo_record_unlinker':
                icon = 'fa-trash';
                label = pick('Eliminando en', 'Eliminó en');
                target = model;
                break;
            case 'odoo_model_method_executor':
                icon = 'fa-cogs';
                label = pick('Ejecutando', 'Ejecutó');
                target = [model, args.method].filter(Boolean).join('.');
                break;
            case 'web_fetch':
            case 'odoo_web_fetch':
                icon = 'fa-globe';
                label = pick('Leyendo', 'Leyó');
                target = hostOf(args.url);
                break;
            case 'odoo_active_screen':
                icon = 'fa-desktop';
                label = pick('Leyendo tu pantalla', 'Leyó tu pantalla');
                break;
            case 'llm_task_status_reporter':
                icon = 'fa-flag-checkered';
                label = pick('Reportando estado', 'Reportó estado');
                break;
            default:
                if (/knowledge|retriev|rag/i.test(name || '')) {
                    icon = 'fa-book';
                    label = pick('Buscando en la base de conocimiento', 'Buscó en la base de conocimiento');
                } else {
                    label = pick('Usando', 'Usó');
                    target = humanize(name);
                }
        }
        var summary = '';
        if (status === 'error') {
            summary = 'falló';
        } else if (status === 'completed') {
            var count = countResult(result);
            if (count !== null) {
                summary = count === 1 ? '1 resultado' : count + ' resultados';
            }
        }
        return { label: label, target: target, icon: icon, summary: summary };
    }

    function formatDuration(ms) {
        var value = Number(ms) || 0;
        if (value < 1000) {
            return (value / 1000).toFixed(1).replace('.', ',') + ' s';
        }
        var seconds = Math.round(value / 1000);
        if (seconds < 60) {
            return seconds + ' s';
        }
        var minutes = Math.floor(seconds / 60);
        var rest = seconds % 60;
        return rest ? minutes + ' min ' + rest + ' s' : minutes + ' min';
    }

    function formatTokens(value) {
        var n = Number(value) || 0;
        if (n >= 1000000) {
            return (n / 1000000).toFixed(1) + 'M';
        }
        if (n >= 1000) {
            return (n / 1000).toFixed(n >= 100000 ? 0 : 1) + 'k';
        }
        return String(n);
    }

    function effortLabel(value) {
        return EFFORT_LABELS[value] || '';
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    /** HTML seguro del razonamiento: sólo **negritas** y saltos de línea. */
    function thinkingToHtml(text) {
        var html = escapeHtml(text || '').trim()
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n{2,}/g, '</p><p>')
            .replace(/\n/g, '<br/>');
        return '<p>' + html + '</p>';
    }

    /** Título del último bloque **…** del razonamiento (lo que «está pensando» ahora). */
    function thinkingHeadline(text) {
        var matches = String(text || '').match(/\*\*(.+?)\*\*/g);
        if (!matches || !matches.length) {
            return '';
        }
        return matches[matches.length - 1].replace(/\*\*/g, '').trim();
    }

    /** Línea de metadatos de una respuesta: esfuerzo · duración · tokens. */
    function responseMetaLine(bodyJson) {
        var data = bodyJson || {};
        var parts = [];
        if (data.reasoning_effort) {
            parts.push(effortLabel(data.reasoning_effort));
        }
        if (data.duration_ms) {
            parts.push(formatDuration(data.duration_ms));
        }
        var usage = data.usage;
        if (usage && (usage.prompt || usage.output)) {
            var tokens = formatTokens(usage.prompt) + ' → ' + formatTokens(usage.output) + ' tokens';
            if (usage.thoughts) {
                tokens += ' · ' + formatTokens(usage.thoughts) + ' razonando';
            }
            parts.push(tokens);
        }
        return parts.filter(Boolean).join(' · ');
    }

    /** Notas del sistema de contexto (resumen / reinicio) publicadas en el hilo. */
    function isContextNoteBody(body) {
        return /Contexto (resumido|reiniciado)/.test(body || '');
    }

    return {
        extraComponents: extraComponents,
        parseToolArgs: parseToolArgs,
        describeToolStep: describeToolStep,
        formatDuration: formatDuration,
        formatTokens: formatTokens,
        effortLabel: effortLabel,
        thinkingToHtml: thinkingToHtml,
        thinkingHeadline: thinkingHeadline,
        responseMetaLine: responseMetaLine,
        isContextNoteBody: isContextNoteBody,
    };
});
