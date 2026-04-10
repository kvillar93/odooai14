odoo.define('llm_generate/static/src/components/llm_chat_composer/llm_chat_composer.js', function (require) {
    'use strict';

    const LLMChatComposer = require('llm_thread/static/src/components/llm_chat_composer/llm_chat_composer.js');
    const LLMMediaForm = require('llm_generate/static/src/components/llm_media_form/llm_media_form.js');

    const BaseComponents = LLMChatComposer.components || {};
    LLMChatComposer.components = Object.assign({}, BaseComponents, {
        LLMMediaForm: LLMMediaForm,
    });

    Object.defineProperty(LLMChatComposer.prototype, 'thread', {
        get: function () {
            const c = this.composer;
            return c ? c.thread : undefined;
        },
        configurable: true,
    });

    Object.defineProperty(LLMChatComposer.prototype, 'isMediaGenerationModel', {
        get: function () {
            const t = this.thread;
            if (!t || !t.llmModel) {
                return false;
            }
            return t.llmModel.isMediaGenerationModel === true;
        },
        configurable: true,
    });

    Object.defineProperty(LLMChatComposer.prototype, 'shouldShowStandardComposer', {
        get: function () {
            return !this.isMediaGenerationModel;
        },
        configurable: true,
    });

    return LLMChatComposer;
});
