odoo.define('llm_generate/static/src/models/llm_chat.js', function (require) {
    'use strict';

    require('llm_thread/static/src/models/llm_chat.js');

    const { registerInstancePatchModel } = require('mail/static/src/model/model_core.js');

    registerInstancePatchModel('mail.llm_chat', 'llm_generate/static/src/models/llm_chat.js', {
        async loadLLMModels() {
            const result = await this.async(function () {
                return this.env.services.rpc({
                    model: 'llm.model',
                    method: 'search_read',
                    kwargs: {
                        domain: [],
                        fields: [
                            'name',
                            'id',
                            'provider_id',
                            'default',
                            'model_use',
                            'details',
                        ],
                    },
                });
            }.bind(this));

            const LLMModel = this.env.models['mail.llm_model'];
            const records = [];
            for (let i = 0; i < result.length; i++) {
                const model = result[i];
                const details = model.details || {};
                const data = {
                    id: model.id,
                    name: model.name,
                    llmProvider: model.provider_id
                        ? { id: model.provider_id[0], name: model.provider_id[1] }
                        : undefined,
                    default: model.default,
                    llmChat: this,
                    modelUse: model.model_use,
                    details: details,
                };
                let rec = LLMModel.findFromIdentifyingData({ id: model.id });
                if (rec) {
                    rec.update(data);
                } else {
                    rec = LLMModel.insert(data);
                }
                records.push(rec);
            }
            this.update({ llmModels: [['replace', records]] });
        },

        async getThreadFormConfiguration() {
            if (!this.activeThread || !this.activeThread.id) {
                return {
                    input_schema: {},
                    form_defaults: {},
                    error: 'No active thread',
                };
            }

            try {
                const result = await this.async(function () {
                    return this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'get_input_schema',
                        args: [this.activeThread.id],
                    });
                }.bind(this));

                const defaults = await this.async(function () {
                    return this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'get_form_defaults',
                        args: [this.activeThread.id],
                    });
                }.bind(this));

                return {
                    input_schema: result || {},
                    form_defaults: defaults || {},
                };
            } catch (error) {
                console.error('Error al obtener la configuración del formulario del hilo:', error);
                return {
                    input_schema: {},
                    form_defaults: {},
                    error: error.message,
                };
            }
        },

        async getModelGenerationIO(modelId) {
            try {
                return await this.async(function () {
                    return this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'get_model_generation_io_by_id',
                        args: [modelId],
                    });
                }.bind(this));
            } catch (error) {
                console.error('Error al obtener E/S de generación del modelo:', error);
                return {
                    error: error.message,
                    input_schema: null,
                    output_schema: null,
                    model_id: modelId,
                    model_name: null,
                };
            }
        },
    });
});
