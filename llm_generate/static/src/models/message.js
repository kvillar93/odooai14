odoo.define('llm_generate/static/src/models/message.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;

    registerFieldPatchModel('mail.message', 'llm_generate/static/src/models/message.js', {
        isLLMUserGenerationMessage: attr({
            compute: '_computeIsLLMUserGenerationMessage',
            dependencies: ['llmRole', 'bodyJson'],
        }),
        generationDataFormatted: attr({
            compute: '_computeGenerationDataFormatted',
            dependencies: ['bodyJson'],
        }),
    });

    registerInstancePatchModel('mail.message', 'llm_generate/static/src/models/message.js', {
        _computeIsLLMUserGenerationMessage: function () {
            return this.llmRole === 'user' && Boolean(this.bodyJson);
        },

        _computeGenerationDataFormatted: function () {
            if (!this.bodyJson || Object.keys(this.bodyJson).length === 0) {
                return '{}';
            }
            try {
                return JSON.stringify(this.bodyJson, null, 2);
            } catch (e) {
                return String(this.bodyJson);
            }
        },
    });
});
