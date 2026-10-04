odoo.define('llm_experience/static/src/js/llm_tool_visibility.js', function (require) {
    'use strict';

    const Message = require('mail/static/src/components/message/message.js');
    const session = require('web.session');

    /**
     * Visibilidad del detalle técnico de las herramientas.
     *
     * Todos los usuarios ven cada paso como una línea compacta (estilo Cursor /
     * ChatGPT). Sólo los usuarios del grupo `llm_experience.group_llm_tool_debug`
     * pueden desplegar los argumentos y el JSON del resultado.
     */
    function _isLlmToolDebug() {
        try {
            return Boolean(session && session.llm_tool_debug);
        } catch (_e) {
            return false;
        }
    }

    if (typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.classList.add(
            _isLlmToolDebug() ? 'o_llm_tool_debug' : 'o_llm_no_tool_debug'
        );
    }

    Object.defineProperty(Message.prototype, 'llmToolDebugEnabled', {
        get: function () {
            return _isLlmToolDebug();
        },
        configurable: true,
    });
});
