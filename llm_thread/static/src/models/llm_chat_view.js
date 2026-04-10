odoo.define('llm_thread/static/src/models/llm_chat_view.js', function (require) {
    'use strict';

    const { registerNewModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;
    const one2one = ModelField.one2one;

    function factory(dependencies) {

        class LLMChatView extends dependencies['mail.model'] {

            _created() {
                this._updateLayoutState();
            }

            _updateLayoutState() {
                if (this.llmChat.isSystrayFloatingMode) {
                    const isSmall = this._isSmall();
                    this.update({
                        isSmall: isSmall,
                        isThreadListVisible: false,
                        isSidebarCollapsed: false,
                    });
                    return;
                }
                const isSmall = this._isSmall();
                const isChatterMode = Boolean(this.llmChat.isChatterMode);

                this.update({
                    isSmall: isSmall,
                    isThreadListVisible: !isSmall,
                    isSidebarCollapsed: isChatterMode,
                });
            }

            _onLLMChatActiveThreadChanged() {
                if (this.llmChat.isSystrayFloatingMode) {
                    return;
                }
                if (this.env.bus && this.actionId) {
                    this.env.bus.trigger('action_manager:update_state', {
                        action: this.actionId,
                        active_id: this.llmChat.activeId,
                    });
                }
            }

            _onContextChanged() {
                this._updateLayoutState();
            }

            _isSmall() {
                const isActuallySmall = this.env.messaging.device.isSmall;
                let isChatterAside = false;
                if (this.llmChat.isChatterMode) {
                    const chatters = this.env.models['mail.chatter'].all();
                    isChatterAside = chatters.some(function (chatter) {
                        return chatter.hasMessageListScrollAdjust;
                    });
                }
                return isActuallySmall || isChatterAside;
            }

            toggleSidebar() {
                this.update({ isSidebarCollapsed: !this.isSidebarCollapsed });
            }

            _computeThreadViewer() {
                if (!this.llmChat.activeThread) {
                    return [['unlink']];
                }
                const ThreadViewer = this.env.models['mail.thread_viewer'];
                const all = ThreadViewer.all();
                let found;
                for (let i = 0; i < all.length; i++) {
                    if (all[i].llmChatView === this) {
                        found = all[i];
                        break;
                    }
                }
                if (found) {
                    return [['link', found]];
                }
                return [['create', {
                    llmChatView: [['link', this]],
                }]];
            }

            _computeThreadView() {
                if (!this.threadViewer) {
                    return [['unlink']];
                }
                var tv = this.threadViewer.threadView;
                return tv ? [['link', tv]] : [['unlink']];
            }

            _computeIsActive() {
                return Boolean(this.llmChat);
            }

            _computeThread() {
                return this.llmChat && this.llmChat.activeThread
                    ? [['link', this.llmChat.activeThread]]
                    : [['unlink']];
            }

            _computeComposer() {
                if (!this.threadViewer || !this.threadViewer.thread) {
                    return [['unlink']];
                }
                var c = this.threadViewer.thread.composer;
                return c ? [['link', c]] : [['unlink']];
            }

            _updateAfter(previous) {
                const curId = this.llmChat && this.llmChat.activeThread && this.llmChat.activeThread.id;
                if (previous.activeThreadId !== curId) {
                    this._onLLMChatActiveThreadChanged();
                }
                const ck = this._contextKey();
                if (previous.contextKey !== ck) {
                    this._onContextChanged();
                }
            }

            _updateBefore() {
                return {
                    activeThreadId: this.llmChat && this.llmChat.activeThread && this.llmChat.activeThread.id,
                    contextKey: this._contextKey(),
                };
            }

            _contextKey() {
                const c = this.llmChat;
                if (!c) {
                    return '';
                }
                return [
                    c.isChatterMode,
                    c.relatedThreadModel,
                    c.relatedThreadId,
                    c.isSystrayFloatingMode,
                ].join('|');
            }
        }

        LLMChatView.modelName = 'mail.llm_chat_view';

        LLMChatView.fields = {
            actionId: attr(),
            isThreadListVisible: attr({ default: true }),
            isSidebarCollapsed: attr({ default: false }),
            isSmall: attr({ default: false }),
            llmChat: one2one('mail.llm_chat', {
                inverse: 'llmChatView',
            }),
            llmChatActiveThread: many2one('mail.thread', {
                related: 'llmChat.activeThread',
            }),
            threadViewerThreadView: one2one('mail.thread_view', {
                related: 'threadViewer.threadView',
            }),
            isActive: attr({
                compute: '_computeIsActive',
                dependencies: ['llmChat'],
            }),
            thread: many2one('mail.thread', {
                compute: '_computeThread',
                dependencies: ['llmChatActiveThread'],
            }),
            threadViewer: one2one('mail.thread_viewer', {
                compute: '_computeThreadViewer',
                dependencies: ['llmChatActiveThread'],
                inverse: 'llmChatView',
            }),
            threadView: one2one('mail.thread_view', {
                compute: '_computeThreadView',
                dependencies: ['threadViewerThreadView'],
            }),
            composer: many2one('mail.composer', {
                compute: '_computeComposer',
                dependencies: ['threadViewerThreadView'],
            }),
        };

        return LLMChatView;
    }

    registerNewModel('mail.llm_chat_view', factory);
});
