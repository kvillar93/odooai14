odoo.define('llm_assistant/static/src/models/thread.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;

    registerFieldPatchModel('mail.thread', 'llm_assistant/static/src/models/thread.js', {
        llmAssistant: many2one('mail.llm_assistant', {
            inverse: 'threads',
        }),
        promptId: attr(),
    });

    registerInstancePatchModel('mail.thread', 'llm_assistant/static/src/models/thread.js', {
        async updateLLMChatThreadSettings(settings) {
            settings = settings || {};
            const assistantId = settings.assistantId;
            const merged = Object.assign({}, settings);
            delete merged.assistantId;
            const baseAdditional = settings.additionalValues || {};
            const additionalValues = Object.assign({}, baseAdditional);
            if (assistantId !== undefined) {
                additionalValues.assistant_id = assistantId || false;
            }
            merged.additionalValues = additionalValues;
            return this._super(merged);
        },
    });
});
