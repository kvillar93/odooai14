odoo.define('llm_thread/static/src/models/llm_provider.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const one2many = ModelField.one2many;
    const many2many = ModelField.many2many;

    function factory(dependencies) {

        class LLMProvider extends dependencies['mail.model'] {

            static _createRecordLocalId(data) {
                return this.modelName + '_' + data.id;
            }
        }

        LLMProvider.modelName = 'mail.llm_provider';

        LLMProvider.fields = {
            id: attr({ default: null }),
            name: attr(),
            llmModels: one2many('mail.llm_model', {
                inverse: 'llmProvider',
            }),
            llmChats: many2many('mail.llm_chat', {
                inverse: 'llmProviders',
            }),
        };

        return LLMProvider;
    }

    registerNewModel('mail.llm_provider', factory);
});
