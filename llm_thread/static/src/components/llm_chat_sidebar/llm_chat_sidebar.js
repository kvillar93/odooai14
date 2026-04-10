odoo.define('llm_thread/static/src/components/llm_chat_sidebar/llm_chat_sidebar.js', function (require) {
    'use strict';

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');
    const LLMChatThreadList = require('llm_thread/static/src/components/llm_chat_thread_list/llm_chat_thread_list.js');

    const { Component } = owl;

    class LLMChatSidebar extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                var record = this.props.record;
                var llmChat = record && record.llmChat;
                return {
                    llmChatView: record && record.__state,
                    llmChat: llmChat && llmChat.__state,
                    threads: llmChat && llmChat.orderedThreads,
                    activeThread: llmChat && llmChat.activeThread,
                };
            }.bind(this));
        }

        get llmChatView() {
            return this.props.record;
        }

        get useDesktopSidebar() {
            const v = this.llmChatView;
            return !v.isSmall && !v.llmChat.isSystrayFloatingMode;
        }

        get useMobileOverlaySidebar() {
            const v = this.llmChatView;
            return v.isSmall || v.llmChat.isSystrayFloatingMode;
        }

        get sidebarWidthStyle() {
            if (!this.useDesktopSidebar) {
                return '';
            }
            return this.llmChatView.isSidebarCollapsed ? 'width: 48px;' : 'width: 280px;';
        }

        _onBackdropClick() {
            if (this.useMobileOverlaySidebar) {
                this.llmChatView.update({ isThreadListVisible: false });
            }
        }

        _onClickToggleSidebar() {
            this.llmChatView.toggleSidebar();
        }

        async _onClickNewChat() {
            const llmChat = this.llmChatView.llmChat;

            if (llmChat.isChatterMode) {
                const thread = await llmChat.createThread({
                    relatedThreadModel: llmChat.relatedThreadModel,
                    relatedThreadId: llmChat.relatedThreadId,
                });

                if (thread) {
                    llmChat.update({ activeThread: [['link', thread]] });

                    if (this.useMobileOverlaySidebar) {
                        this.llmChatView.update({ isThreadListVisible: false });
                    }
                }
            } else {
                await llmChat.createNewThread();
                if (this.useMobileOverlaySidebar) {
                    this.llmChatView.update({ isThreadListVisible: false });
                }
            }
        }
    }

    Object.assign(LLMChatSidebar, {
        props: { record: Object },
        components: {
            LLMChatThreadList: LLMChatThreadList,
        },
        template: 'llm_thread.LLMChatSidebar',
    });

    return LLMChatSidebar;
});
