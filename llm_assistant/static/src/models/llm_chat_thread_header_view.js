odoo.define('llm_assistant/static/src/models/llm_chat_thread_header_view.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;

    registerFieldPatchModel('mail.llm_chat_thread_header_view', 'llm_assistant/static/src/models/llm_chat_thread_header_view.js', {
        selectedAssistantId: attr(),
        selectedAssistant: many2one('mail.llm_assistant', {
            compute: '_computeSelectedAssistant',
            dependencies: ['selectedAssistantId', 'threadView'],
        }),
    });

    registerInstancePatchModel('mail.llm_chat_thread_header_view', 'llm_assistant/static/src/models/llm_chat_thread_header_view.js', {
        _computeSelectedAssistant: function () {
            if (!this.selectedAssistantId) {
                return clear();
            }
            const assistants = this.threadView && this.threadView.thread && this.threadView.thread.llmChat
                ? this.threadView.thread.llmChat.llmAssistants
                : null;
            if (!assistants || !assistants.length) {
                return clear();
            }
            for (let i = 0; i < assistants.length; i++) {
                const assistantRecord = assistants[i];
                if (assistantRecord && assistantRecord.id === this.selectedAssistantId) {
                    return [['link', assistantRecord]];
                }
            }
            return clear();
        },

        _initializeState: function () {
            this._super();
            const currentThread = this.threadView && this.threadView.thread;
            if (!currentThread) {
                this.update({
                    selectedAssistantId: clear(),
                });
                return;
            }
            this.update({
                selectedAssistantId: currentThread.llmAssistant && currentThread.llmAssistant.id
                    ? currentThread.llmAssistant.id
                    : clear(),
            });
        },

        async saveSelectedAssistant(assistantId) {
            if (assistantId === this.selectedAssistantId) {
                return;
            }

            this.update({
                selectedAssistantId: assistantId || clear(),
            });

            const thread = this.threadView.thread;
            const result = await this.async(function () {
                return this.env.services.rpc({
                    route: '/llm/thread/set_assistant',
                    params: {
                        thread_id: thread.id,
                        assistant_id: assistantId,
                    },
                });
            }.bind(this));

            if (result.success) {
                const assistants = this.threadView && this.threadView.thread && this.threadView.thread.llmChat
                    ? this.threadView.thread.llmChat.llmAssistants
                    : null;

                if (assistants && assistantId) {
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
                    }
                }

                await this.threadView.thread.llmChat.refreshThread(this.threadView.thread.id);
                if (assistantId === false) {
                    this.update({
                        selectedAssistantId: clear(),
                    });
                } else {
                    const m = this.threadView.thread.llmModel;
                    this.update({
                        selectedModelId: m && m.id ? m.id : clear(),
                        selectedProviderId: m && m.llmProvider && m.llmProvider.id
                            ? m.llmProvider.id
                            : clear(),
                    });
                }
            } else {
                this.update({
                    selectedAssistantId: this.threadView.thread.llmAssistant && this.threadView.thread.llmAssistant.id
                        ? this.threadView.thread.llmAssistant.id
                        : clear(),
                });
                this.env.services.notification.notify({
                    type: 'warning',
                    message: this.env._t('No se pudo actualizar el asistente'),
                });
            }
        },
    });
});
