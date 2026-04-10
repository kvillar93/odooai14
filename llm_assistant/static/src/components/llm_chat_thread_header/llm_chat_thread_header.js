odoo.define('llm_assistant/static/src/components/llm_chat_thread_header/llm_chat_thread_header.js', function (require) {
    'use strict';

    const LLMChatThreadHeader = require('llm_thread/static/src/components/llm_chat_thread_header/llm_chat_thread_header.js');

    Object.defineProperty(LLMChatThreadHeader.prototype, 'llmAssistants', {
        get: function () {
            if (!this.llmChat) {
                return [];
            }
            return this.llmChat.llmAssistants || [];
        },
        configurable: true,
    });

    Object.defineProperty(LLMChatThreadHeader.prototype, 'compactAssistantTitle', {
        get: function () {
            const a = this.llmChatThreadHeaderView.selectedAssistant;
            if (a) {
                return this.env._t('Asistente predefinido') + ': ' + a.name;
            }
            return this.env._t('Sin asistente predefinido');
        },
        configurable: true,
    });

    LLMChatThreadHeader.prototype.onClearAssistant = function () {
        this.llmChatThreadHeaderView.saveSelectedAssistant(false);
    };

    /**
     * Se usa desde la plantilla con data-assistant-id (OWL 1 / QWeb).
     */
    LLMChatThreadHeader.prototype.onSelectAssistantFromEvent = function (ev) {
        if (ev) {
            ev.preventDefault();
        }
        const raw = ev && ev.currentTarget && ev.currentTarget.getAttribute('data-assistant-id');
        const id = raw ? parseInt(raw, 10) : NaN;
        if (!isNaN(id)) {
            this.llmChatThreadHeaderView.saveSelectedAssistant(id);
        }
    };

    return LLMChatThreadHeader;
});
