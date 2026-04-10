odoo.define('llm_assistant/static/src/models/llm_assistant_record.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;
    const one2many = ModelField.one2many;

    function factory(dependencies) {

        class LLMAssistant extends dependencies['mail.model'] {

            static _createRecordLocalId(data) {
                return this.modelName + '_' + data.id;
            }
        }

        LLMAssistant.modelName = 'mail.llm_assistant';

        LLMAssistant.fields = {
            id: attr({ default: null }),
            name: attr(),
            isDefault: attr({ default: false }),
            threads: one2many('mail.thread', {
                inverse: 'llmAssistant',
            }),
            llmPrompt: many2one('mail.llm_prompt', {
                inverse: 'assistants',
            }),
            promptId: attr(),
            defaultValues: attr(),
            evaluatedDefaultValues: attr(),
            llmChat: many2one('mail.llm_chat', {
                inverse: 'llmAssistants',
            }),
        };

        return LLMAssistant;
    }

    registerNewModel('mail.llm_assistant', factory);
});
