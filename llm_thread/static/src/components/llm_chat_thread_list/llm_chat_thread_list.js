odoo.define('llm_thread/static/src/components/llm_chat_thread_list/llm_chat_thread_list.js', function (require) {
    'use strict';

    const Dialog = require('web.Dialog');
    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');

    const { Component } = owl;
    const { useState } = owl.hooks;

    class LLMChatThreadList extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                var record = this.props.record;
                var llmChat = record && record.llmChat;
                return {
                    llmChatView: record && record.__state,
                    llmChat: llmChat && llmChat.__state,
                    orderedThreads: llmChat && llmChat.orderedThreads,
                    activeThread: llmChat && llmChat.activeThread,
                };
            }.bind(this));
            this.state = useState({
                isLoading: false,
                searchQuery: '',
            });
        }

        onSearchInput(ev) {
            this.state.searchQuery = ev.target.value || '';
        }

        get filteredThreads() {
            const threads = this.llmChatView.llmChat.orderedThreads || [];
            const q = (this.state.searchQuery || '').trim().toLowerCase();
            if (!q) {
                return threads;
            }
            return threads.filter(function (t) {
                return (t.name || '').toLowerCase().includes(q);
            });
        }

        get llmChatView() {
            return this.props.record;
        }

        get messaging() {
            return this.llmChatView.messaging;
        }

        get activeThread() {
            return this.llmChatView.llmChat.activeThread;
        }

        async _onThreadClick(thread) {
            if (this.state.isLoading) {
                return;
            }

            this.state.isLoading = true;
            try {
                await this.llmChatView.llmChat.selectThread(thread.id);
                this.llmChatView.update({
                    isThreadListVisible: false,
                });
            } catch (error) {
                console.error('Error selecting thread:', error);
                this.env.services.notification.notify({
                    title: 'Error',
                    message: 'No se pudo cargar la conversación',
                    type: 'danger',
                });
            } finally {
                this.state.isLoading = false;
            }
        }

        _onDeleteClick(ev, thread) {
            ev.preventDefault();
            ev.stopPropagation();
            const self = this;
            Dialog.confirm(this, self.env._t('¿Eliminar esta conversación de forma permanente? Esta acción no se puede deshacer.'), {
                title: self.env._t('Eliminar conversación'),
                confirm_callback: function () {
                    self._unlinkThread(thread);
                },
            });
        }

        async _unlinkThread(thread) {
            const llmChat = this.llmChatView.llmChat;
            const deletedId = thread.id;
            const wasActive = llmChat.activeThread && llmChat.activeThread.id === deletedId;
            try {
                await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'unlink',
                    args: [[deletedId]],
                });
                await llmChat.loadThreads();
                if (wasActive) {
                    const remaining = llmChat.orderedThreads;
                    if (remaining.length > 0) {
                        await llmChat.selectThread(remaining[0].id);
                    } else {
                        await llmChat.createNewThread();
                    }
                }
            } catch (e) {
                console.error(e);
                this.env.services.notification.notify({
                    message: this.env._t('No se pudo eliminar la conversación'),
                    type: 'danger',
                });
            }
        }
    }

    Object.assign(LLMChatThreadList, {
        props: { record: Object },
        template: 'llm_thread.LLMChatThreadList',
    });

    return LLMChatThreadList;
});
