odoo.define('llm_thread/static/src/models/llm_tool.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;

    function factory(dependencies) {

        class LLMTool extends dependencies['mail.model'] {

            static _createRecordLocalId(data) {
                return this.modelName + '_' + data.id;
            }
        }

        LLMTool.modelName = 'mail.llm_tool';

        LLMTool.fields = {
            id: attr({ default: null }),
            name: attr(),
            default: attr({ default: false }),
            llmChat: many2one('mail.llm_chat', {
                inverse: 'tools',
            }),
        };

        return LLMTool;
    }

    registerNewModel('mail.llm_tool', factory);
});
