odoo.define('llm_assistant/static/src/models/llm_prompt.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const one2many = ModelField.one2many;

    function factory(dependencies) {

        class LLMPrompt extends dependencies['mail.model'] {

            static _createRecordLocalId(data) {
                return this.modelName + '_' + data.id;
            }
        }

        LLMPrompt.modelName = 'mail.llm_prompt';

        LLMPrompt.fields = {
            id: attr({ default: null }),
            name: attr(),
            inputSchemaJson: attr({ default: '{}' }),
            assistants: one2many('mail.llm_assistant', {
                inverse: 'llmPrompt',
            }),
        };

        return LLMPrompt;
    }

    registerNewModel('mail.llm_prompt', factory);
});
