odoo.define('llm_experience/static/src/components/llm_chat_composer_experience/llm_chat_composer_experience.js', function (require) {
    'use strict';

    const { registerInstancePatchModel } = require('mail/static/src/model/model_core.js');

    const LLMChatComposer = require('llm_thread/static/src/components/llm_chat_composer/llm_chat_composer.js');
    const LLMContextMeter = require('llm_experience/static/src/components/llm_context_meter/llm_context_meter.js');

    LLMChatComposer.components = Object.assign({}, LLMChatComposer.components || {}, {
        LLMContextMeter: LLMContextMeter,
    });

    function _refreshMeter() {
        window.dispatchEvent(new CustomEvent('llm-experience-refresh-meter'));
    }

    registerInstancePatchModel('mail.composer', 'llm_experience/static/src/components/llm_chat_composer_experience/llm_chat_composer_experience.js', {
        async postUserMessageForLLM() {
            await this._super.apply(this, arguments);
            if (this.thread && this.thread.model === 'llm.thread') {
                _refreshMeter();
            }
        },

        _dispatchStreamEvent: function (data) {
            this._super.apply(this, arguments);
            if (
                this.thread &&
                this.thread.model === 'llm.thread' &&
                (data.type === 'done' || data.type === 'error')
            ) {
                _refreshMeter();
            }
        },
    });
});
