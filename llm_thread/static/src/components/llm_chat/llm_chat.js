odoo.define('llm_thread/static/src/components/llm_chat/llm_chat.js', function (require) {
    'use strict';

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');
    const LLMChatSidebar = require('llm_thread/static/src/components/llm_chat_sidebar/llm_chat_sidebar.js');
    const LLMChatThread = require('llm_thread/static/src/components/llm_chat_thread/llm_chat_thread.js');

    const { Component } = owl;

    class LLMChat extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                var record = this.props.record;
                var llmChat = record && record.llmChat;
                var threadViewer = record && record.threadViewer;
                var threadView = record && record.threadView;
                return {
                    llmChatView: record && record.__state,
                    llmChat: llmChat && llmChat.__state,
                    activeThread: llmChat && llmChat.activeThread,
                    threadViewer: threadViewer && threadViewer.__state,
                    threadView: threadView && threadView.__state,
                };
            }.bind(this));
        }

        get llmChatView() {
            return this.props.record;
        }
    }

    Object.assign(LLMChat, {
        props: { record: Object },
        components: {
            LLMChatSidebar: LLMChatSidebar,
            LLMChatThread: LLMChatThread,
        },
        template: 'llm_thread.LLMChat',
    });

    return LLMChat;
});
