odoo.define('llm_thread/static/src/models/llm_model.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;
    const one2many = ModelField.one2many;

    function factory(dependencies) {

        class LLMModel extends dependencies['mail.model'] {

            static _createRecordLocalId(data) {
                return this.modelName + '_' + data.id;
            }
        }

        LLMModel.modelName = 'mail.llm_model';

        LLMModel.fields = {
            id: attr({ default: null }),
            name: attr(),
            llmProvider: many2one('mail.llm_provider', {
                inverse: 'llmModels',
            }),
            threads: one2many('mail.thread', {
                inverse: 'llmModel',
            }),
            default: attr({ default: false }),
            llmChat: many2one('mail.llm_chat', {
                inverse: 'llmModels',
            }),
        };

        return LLMModel;
    }

    registerNewModel('mail.llm_model', factory);
});
