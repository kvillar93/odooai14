odoo.define('llm_thread/static/src/components/llm_chat_container/llm_chat_container.js', function (require) {
    'use strict';

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');

    const LLMChat = require('llm_thread/static/src/components/llm_chat/llm_chat.js');

    const { Component } = owl;
    const { onWillUnmount } = owl.hooks;

    class LLMChatContainer extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                var messaging = this.env.messaging;
                var llmChat = messaging && messaging.llmChat;
                var llmChatView = llmChat && llmChat.llmChatView;
                return {
                    messaging: messaging && messaging.__state,
                    isInitialized: messaging && messaging.isInitialized,
                    llmChat: llmChat && llmChat.__state,
                    llmChatView: llmChatView && llmChatView.__state,
                };
            }.bind(this));

            const self = this;
            onWillUnmount(function () {
                self._willDestroy();
            });

            this.env.messagingCreatedPromise.then(async function () {
                const action = this.props.action;
                let initActiveId = null;
                if (action) {
                    if (action.context && action.context.active_id) {
                        initActiveId = action.context.active_id;
                    } else if (action.context && action.context.default_active_id) {
                        initActiveId = action.context.default_active_id;
                    } else if (action.params && action.params.default_active_id) {
                        initActiveId = action.params.default_active_id;
                    } else if (action.params && action.params.active_id) {
                        initActiveId = action.params.active_id;
                    }
                }

                const messaging = this.env.messaging;
                if (!messaging.llmChat) {
                    messaging.update({
                        llmChat: [['create', {
                            isInitThreadHandled: false,
                        }]],
                    });
                }
                this.llmChat = messaging.llmChat;
                await this.llmChat.initializeLLMChat(action, initActiveId);
            }.bind(this));

            LLMChatContainer.currentInstance = this;
        }

        get messaging() {
            return this.env.messaging;
        }

        _willDestroy() {
            if (this.llmChat && LLMChatContainer.currentInstance === this) {
                this.llmChat.close();
            }
        }
    }

    LLMChatContainer.currentInstance = null;

    Object.assign(LLMChatContainer, {
        props: {
            action: Object,
            actionId: { type: Number, optional: true },
            className: String,
            globalState: { type: Object, optional: true },
        },
        components: {
            LLMChat: LLMChat,
        },
        template: 'llm_thread.LLMChatContainer',
    });

    return LLMChatContainer;
});
