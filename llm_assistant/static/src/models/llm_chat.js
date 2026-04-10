odoo.define('llm_assistant/static/src/models/llm_chat.js', function (require) {
    'use strict';

    // Registrar mail.llm_chat (llm_thread) antes de parches.
    require('llm_thread/static/src/models/llm_chat.js');

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');

    const one2many = ModelField.one2many;

    const ASSISTANT_THREAD_FIELDS = ['assistant_id', 'prompt_id'];

    registerFieldPatchModel('mail.llm_chat', 'llm_assistant/static/src/models/llm_chat.js', {
        llmAssistants: one2many('mail.llm_assistant', {
            inverse: 'llmChat',
        }),
    });

    registerInstancePatchModel('mail.llm_chat', 'llm_assistant/static/src/models/llm_chat.js', {
        _updateBefore: function () {
            const previous = this._super();
            return Object.assign({}, previous, {
                _assistantActiveThreadId: this.activeThread && this.activeThread.id,
            });
        },

        _updateAfter: function (previous) {
            this._super(previous);
            const curId = this.activeThread && this.activeThread.id;
            if (previous._assistantActiveThreadId !== curId) {
                this._onAssistantActiveThreadChanged();
            }
        },

        _onAssistantActiveThreadChanged: function () {
            if (!this.activeId) {
                return;
            }
            let model;
            let id;
            if (typeof this.activeId === 'number') {
                model = 'llm.thread';
                id = this.activeId;
            } else {
                const parts = String(this.activeId).split('_');
                model = parts[0];
                id = Number(parts[1]);
            }
            const Thread = this.env.models['mail.thread'];
            const activeThread = Thread.findFromIdentifyingData({
                id: id,
                model: model,
            });
            if (!activeThread || !activeThread.llmAssistant) {
                return;
            }
            this._fetchAssistantValuesForThread(
                activeThread.id,
                activeThread.llmAssistant.id
            );
        },

        async loadAssistants() {
            const assistantResult = await this.async(function () {
                return this.env.services.rpc({
                    model: 'llm.assistant',
                    method: 'search_read',
                    kwargs: {
                        domain: [['active', '=', true]],
                        fields: ['name', 'default_values', 'prompt_id', 'is_default'],
                    },
                });
            }.bind(this));

            const promptIds = assistantResult
                .map(function (assistant) {
                    return assistant.prompt_id && assistant.prompt_id[0];
                })
                .filter(function (id) { return id; });

            let promptsById = {};
            if (promptIds.length > 0) {
                const promptResult = await this.async(function () {
                    return this.env.services.rpc({
                        model: 'llm.prompt',
                        method: 'search_read',
                        kwargs: {
                            domain: [['id', 'in', promptIds]],
                            fields: ['name', 'input_schema_json'],
                        },
                    });
                }.bind(this));

                promptsById = promptResult.reduce(function (acc, prompt) {
                    acc[prompt.id] = {
                        id: prompt.id,
                        name: prompt.name,
                        inputSchemaJson: prompt.input_schema_json,
                    };
                    return acc;
                }, {});
            }

            const LLMAssistant = this.env.models['mail.llm_assistant'];
            const LLMPrompt = this.env.models['mail.llm_prompt'];
            const records = [];

            for (let i = 0; i < assistantResult.length; i++) {
                const assistant = assistantResult[i];
                const data = {
                    id: assistant.id,
                    name: assistant.name,
                    isDefault: Boolean(assistant.is_default),
                    defaultValues: assistant.default_values,
                    llmChat: [['link', this]],
                };

                if (assistant.prompt_id && assistant.prompt_id[0]) {
                    const promptId = assistant.prompt_id[0];
                    data.promptId = promptId;
                    if (promptsById[promptId]) {
                        const p = promptsById[promptId];
                        let pr = LLMPrompt.findFromIdentifyingData({ id: p.id });
                        if (!pr) {
                            pr = LLMPrompt.insert({
                                id: p.id,
                                name: p.name,
                                inputSchemaJson: p.inputSchemaJson,
                            });
                        } else {
                            pr.update({
                                name: p.name,
                                inputSchemaJson: p.inputSchemaJson,
                            });
                        }
                        data.llmPrompt = [['link', pr]];
                    }
                }

                let rec = LLMAssistant.findFromIdentifyingData({ id: data.id });
                if (rec) {
                    rec.update(data);
                } else {
                    rec = LLMAssistant.insert(data);
                }
                records.push(rec);
            }

            this.update({ llmAssistants: [['replace', records]] });
        },

        async ensureDataLoaded() {
            await this._super();
            if (!this.llmAssistants || this.llmAssistants.length === 0) {
                await this.loadAssistants();
            }
        },

        async initializeLLMChat(action, initActiveId, postInitializationPromises) {
            postInitializationPromises = postInitializationPromises || [];
            const promises = postInitializationPromises.slice();
            promises.push(this.loadAssistants());
            return this._super(action, initActiveId, promises);
        },

        async loadThreads(additionalFields, domain) {
            additionalFields = additionalFields || [];
            return this._super(
                additionalFields.concat(ASSISTANT_THREAD_FIELDS),
                domain
            );
        },

        async refreshThread(threadId, additionalFields) {
            additionalFields = additionalFields || [];
            return this._super(threadId, additionalFields.concat(ASSISTANT_THREAD_FIELDS));
        },

        _mapThreadDataFromServer: function (threadData) {
            const mappedData = this._super(threadData);
            if (threadData.assistant_id) {
                mappedData.llmAssistant = [['insert', {
                    id: threadData.assistant_id[0],
                    name: threadData.assistant_id[1],
                }]];
            } else {
                mappedData.llmAssistant = clear();
            }
            return mappedData;
        },

        async selectThread(threadId) {
            await this._super(threadId);
            const Thread = this.env.models['mail.thread'];
            const thread = Thread.findFromIdentifyingData({
                id: threadId,
                model: 'llm.thread',
            });
            if (thread && thread.llmAssistant && thread.llmAssistant.id) {
                await this._fetchAssistantValuesForThread(thread.id, thread.llmAssistant.id);
            }
        },

        async _fetchAssistantValuesForThread(threadId, assistantId) {
            try {
                const result = await this.async(function () {
                    return this.env.services.rpc({
                        route: '/llm/thread/get_assistant_values',
                        params: {
                            thread_id: threadId,
                            assistant_id: assistantId,
                        },
                    });
                }.bind(this));

                if (result.success) {
                    const Thread = this.env.models['mail.thread'];
                    const LLMPrompt = this.env.models['mail.llm_prompt'];
                    const thread = Thread.findFromIdentifyingData({
                        id: threadId,
                        model: 'llm.thread',
                    });
                    if (thread) {
                        const assistants = this.llmAssistants || [];
                        let assistant = null;
                        for (let i = 0; i < assistants.length; i++) {
                            if (assistants[i] && assistants[i].id === assistantId) {
                                assistant = assistants[i];
                                break;
                            }
                        }
                        if (assistant) {
                            if (result.evaluated_default_values) {
                                assistant.update({
                                    defaultValues: result.default_values,
                                    evaluatedDefaultValues: result.evaluated_default_values,
                                });
                            } else {
                                assistant.update({
                                    defaultValues: clear(),
                                    evaluatedDefaultValues: clear(),
                                });
                            }

                            if (result.prompt) {
                                const promptData = result.prompt;
                                let prompt = LLMPrompt.findFromIdentifyingData({
                                    id: promptData.id,
                                });
                                if (prompt) {
                                    prompt.update({
                                        name: promptData.name,
                                        inputSchemaJson: promptData.input_schema_json,
                                    });
                                } else {
                                    LLMPrompt.insert({
                                        id: promptData.id,
                                        name: promptData.name,
                                        inputSchemaJson: promptData.input_schema_json,
                                    });
                                }
                                var promptRec = LLMPrompt.findFromIdentifyingData({ id: promptData.id });
                                assistant.update({
                                    promptId: promptData.id,
                                    llmPrompt: promptRec ? [['link', promptRec]] : [['insert', { id: promptData.id }]],
                                });
                            }
                        }
                    }
                } else {
                    console.error('Error al obtener valores del asistente:', result.error);
                }
            } catch (error) {
                console.error('Error en _fetchAssistantValuesForThread:', error);
            }
        },
    });
});
