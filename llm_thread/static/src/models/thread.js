odoo.define('llm_thread/static/src/models/thread.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    const attr = ModelField.attr;
    const many2many = ModelField.many2many;
    const many2one = ModelField.many2one;
    const one2many = ModelField.one2many;

    function camelToSnakeCase(str) {
        return str.replace(/[A-Z]/g, function (letter) {
            return '_' + letter.toLowerCase();
        });
    }

    registerFieldPatchModel('mail.thread', 'llm_thread/static/src/models/thread.js', {
        llmChat: many2one('mail.llm_chat', {
            inverse: 'threads',
        }),
        activeLLMChat: one2many('mail.llm_chat', {
            inverse: 'activeThread',
        }),
        llmModel: many2one('mail.llm_model', {
            inverse: 'threads',
        }),
        updatedAt: attr(),
        relatedThreadModel: attr(),
        relatedThreadId: attr(),
        relatedThread: many2one('mail.thread', {
            compute: '_computeRelatedThread',
            dependencies: ['relatedThreadModel', 'relatedThreadId'],
        }),
        selectedToolIds: attr({
            default: [],
        }),
        selectedTools: many2many('mail.llm_tool', {
            compute: '_computeSelectedTools',
            dependencies: ['selectedToolIds', 'llmChat'],
        }),
        chatWindowId: attr({ default: null }),
        hideThreadSettings: attr({ default: false }),
        llmChatOrderedThreads: many2many('mail.llm_chat', {
            inverse: 'orderedThreads',
        }),
    });

    registerInstancePatchModel('mail.thread', 'llm_thread/static/src/models/thread.js', {
        _computeRelatedThread() {
            if (!this.relatedThreadModel || !this.relatedThreadId) {
                return clear();
            }
            const Thread = this.env.models['mail.thread'];
            const existing = Thread.findFromIdentifyingData({
                model: this.relatedThreadModel,
                id: this.relatedThreadId,
            });
            return existing ? [['link', existing]] : clear();
        },

        _computeSelectedTools() {
            if (!this.selectedToolIds || !this.llmChat || !this.llmChat.tools) {
                return clear();
            }
            const tools = this.llmChat.tools.filter(function (tool) {
                return this.selectedToolIds.includes(tool.id);
            }.bind(this));
            return [['replace', tools]];
        },

        async openLLMThread(options) {
            options = options || {};
            const focus = options.focus !== false;
            if (this.model !== 'llm.thread') {
                return;
            }

            const messaging = this.env.messaging;
            let llmChat = messaging.llmChat;

            if (!llmChat) {
                messaging.update({ llmChat: [['create', { isInitThreadHandled: false }]] });
                llmChat = messaging.llmChat;
            }

            await llmChat.ensureDataLoaded();

            if (!llmChat.llmChatView) {
                await this.async(function () {
                    return llmEnvUtils.waitMessagingReady(this.env);
                }.bind(this));
                llmChat.open();
            }

            llmChat.update({ activeThread: [['link', this]] });

            if (focus && llmChat.llmChatView && llmChat.llmChatView.composer) {
                const composer = llmChat.llmChatView.composer;
                for (let i = 0; i < composer.composerViews.length; i++) {
                    composer.composerViews[i].update({ doFocus: true });
                }
            }
        },

        async updateLLMChatThreadSettings(settings) {
            settings = settings || {};
            const name = settings.name;
            const llmModelId = settings.llmModelId;
            const llmProviderId = settings.llmProviderId;
            const toolIds = settings.toolIds;
            const additionalValues = settings.additionalValues || {};

            const values = Object.assign({}, additionalValues);

            if (typeof name === 'string' && name.trim()) {
                values.name = name.trim();
            }

            if (Number.isInteger(llmModelId) && llmModelId > 0) {
                values.model_id = llmModelId;
            } else if (this.llmModel && this.llmModel.id) {
                values.model_id = this.llmModel.id;
            }

            if (Number.isInteger(llmProviderId) && llmProviderId > 0) {
                values.provider_id = llmProviderId;
            } else if (this.llmModel && this.llmModel.llmProvider && this.llmModel.llmProvider.id) {
                values.provider_id = this.llmModel.llmProvider.id;
            }

            if (Array.isArray(toolIds)) {
                values.tool_ids = [[6, 0, toolIds]];
            }

            if (Object.keys(values).length > 0) {
                await this.async(function () {
                    return this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'write',
                        args: [[this.id], values],
                    });
                }.bind(this));

                if (this.llmChat) {
                    const additionalFields = Object.keys(additionalValues).map(function (key) {
                        if (key.indexOf('_') >= 0) {
                            return key;
                        }
                        return camelToSnakeCase(key);
                    });
                    await this.llmChat.refreshThread(this.id, additionalFields);
                }
            }
        },
    });
});
