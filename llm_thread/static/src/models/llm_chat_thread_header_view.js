odoo.define('llm_thread/static/src/models/llm_chat_thread_header_view.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    const attr = ModelField.attr;
    const many2many = ModelField.many2many;
    const many2one = ModelField.many2one;
    const one2one = ModelField.one2one;

    function factory(dependencies) {

        class LLMChatThreadHeaderView extends dependencies['mail.model'] {

            _created() {
                this._initializeState();
            }

            _initializeState() {
                const currentThread = this.threadView && this.threadView.thread;
                if (!currentThread) {
                    this.update({
                        selectedProviderId: clear(),
                        selectedModelId: clear(),
                    });
                    return;
                }

                this.update({
                    selectedProviderId: currentThread.llmModel && currentThread.llmModel.llmProvider
                        ? currentThread.llmModel.llmProvider.id
                        : clear(),
                    selectedModelId: currentThread.llmModel ? currentThread.llmModel.id : clear(),
                });
            }

            _onThreadViewChange() {
                this._initializeState();
            }

            _updateAfter(previous) {
                const curId = this.threadView && this.threadView.thread && this.threadView.thread.id;
                if (previous.threadId !== curId) {
                    this._onThreadViewChange();
                }
            }

            _updateBefore() {
                return {
                    threadId: this.threadView && this.threadView.thread && this.threadView.thread.id,
                };
            }

            async saveSelectedModel(selectedModelId) {
                if (!selectedModelId || selectedModelId === this.selectedModelId) {
                    return;
                }

                this.update({
                    selectedModelId: selectedModelId,
                });
                const provider = this.selectedModel.llmProvider;
                this.update({
                    selectedProviderId: provider.id,
                });

                await this.threadView.thread.updateLLMChatThreadSettings({
                    llmModelId: this.selectedModel.id,
                    llmProviderId: provider.id,
                });
            }

            async openThreadSettings() {
                const self = this;
                this.env.bus.trigger('do-action', {
                    action: {
                        type: 'ir.actions.act_window',
                        res_model: 'llm.thread',
                        res_id: this.threadView.thread.id,
                        views: [[false, 'form']],
                        target: 'new',
                        flags: {
                            mode: 'edit',
                        },
                    },
                    options: {
                        on_close: function () {
                            const llmChat = self.threadView.thread.llmChat;
                            const domain = [];
                            if (llmChat.isChatterMode) {
                                domain.push(['model', '=', llmChat.relatedThreadModel]);
                                domain.push(['res_id', '=', llmChat.relatedThreadId]);
                            }
                            llmChat.loadThreads([], domain);
                        },
                    },
                });
            }

            onClickTopbarThreadName() {
                if (!this.threadView || !this.threadView.thread) {
                    return;
                }
                const isSmall = (this.threadView.thread.llmChat && this.threadView.thread.llmChat.llmChatView &&
                    this.threadView.thread.llmChat.llmChatView.isSmall) ||
                    this.env.messaging.device.isSmall;
                if (this.isEditingName || isSmall) {
                    return;
                }
                const t = this.threadView.thread;
                const nm = t.name && String(t.name).trim() ? t.name : (t.id ? 'Chat #' + t.id : '');
                this.update({
                    isEditingName: true,
                    pendingName: nm,
                });
            }

            async saveThreadName() {
                if (!this.threadView || !this.threadView.thread) {
                    this.discardThreadNameEdition();
                    return;
                }
                const thread = this.threadView.thread;
                if (!this.pendingName.trim()) {
                    this.discardThreadNameEdition();
                    return;
                }

                const newName = this.pendingName.trim();
                if (newName === thread.name) {
                    this.discardThreadNameEdition();
                    return;
                }

                try {
                    await thread.updateLLMChatThreadSettings({ name: newName });
                    this.update({
                        isEditingName: false,
                        pendingName: '',
                    });
                } catch (error) {
                    console.error('Error updating thread name:', error);
                    llmEnvUtils.llmNotify(this.env, {
                        message: this.env._t('No se pudo actualizar el nombre del hilo'),
                        type: 'danger',
                    });
                    this.discardThreadNameEdition();
                }
            }

            discardThreadNameEdition() {
                this.update({
                    isEditingName: false,
                    pendingName: '',
                });
            }

            _computeSelectedProvider() {
                if (!this.selectedProviderId) {
                    return clear();
                }
                const providers = this.threadView && this.threadView.thread && this.threadView.thread.llmChat
                    ? this.threadView.thread.llmChat.llmProviders
                    : null;
                if (!providers || !providers.length) {
                    return clear();
                }
                const found = providers.find(function (p) { return p && p.id === this.selectedProviderId; }.bind(this));
                return found ? [['link', found]] : clear();
            }

            _computeSelectedModel() {
                if (!this.selectedModelId) {
                    return clear();
                }
                const models = this.threadView && this.threadView.thread && this.threadView.thread.llmChat
                    ? this.threadView.thread.llmChat.llmModels
                    : null;
                if (!models || !models.length) {
                    return clear();
                }
                const matchedModel = models.find(function (m) { return m && m.id === this.selectedModelId; }.bind(this));
                return matchedModel ? [['link', matchedModel]] : clear();
            }

            _computeModelsAvailableToSelect() {
                if (!this.selectedProviderId) {
                    return [['replace', []]];
                }
                const llmModels = this.threadView && this.threadView.thread && this.threadView.thread.llmChat
                    ? this.threadView.thread.llmChat.llmModels
                    : [];
                const filtered = (llmModels || []).filter(function (model) {
                    return model && model.llmProvider && model.llmProvider.id === this.selectedProviderId;
                }.bind(this));
                return [['replace', filtered]];
            }
        }

        LLMChatThreadHeaderView.modelName = 'mail.llm_chat_thread_header_view';

        LLMChatThreadHeaderView.fields = {
            threadView: one2one('mail.thread_view', {
                inverse: 'llmChatThreadHeaderView',
            }),
            isEditingName: attr({ default: false }),
            pendingName: attr({ default: '' }),
            llmChatThreadNameInputRef: attr(),
            selectedProviderId: attr(),
            selectedModelId: attr(),
            _isInitializing: attr({ default: false }),
            selectedProvider: many2one('mail.llm_provider', {
                compute: '_computeSelectedProvider',
                dependencies: ['selectedProviderId', 'threadView'],
            }),
            selectedModel: many2one('mail.llm_model', {
                compute: '_computeSelectedModel',
                dependencies: ['selectedModelId', 'threadView'],
            }),
            modelsAvailableToSelect: many2many('mail.llm_model', {
                compute: '_computeModelsAvailableToSelect',
                dependencies: ['selectedProviderId', 'threadView'],
            }),
        };

        return LLMChatThreadHeaderView;
    }

    registerNewModel('mail.llm_chat_thread_header_view', factory);
});
