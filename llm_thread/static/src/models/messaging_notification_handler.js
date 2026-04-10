odoo.define('llm_thread/static/src/models/messaging_notification_handler.js', function (require) {
    'use strict';

    const { clear } = require('mail/static/src/model/model_field_command.js');
    const { registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    registerInstancePatchModel('mail.messaging_notification_handler', 'llm_thread/static/src/models/messaging_notification_handler.js', {
        /**
         * @override
         */
        async _handleNotificationPartner(data) {
            const type = data.type;
            if (type === 'llm.thread/delete') {
                return this._handleLLMThreadsDelete(data);
            }
            if (type === 'llm.thread/open_in_chatter') {
                return this._handleLLMThreadOpenInChatter(data);
            }
            return this._super.apply(this, arguments);
        },

        _handleLLMThreadsDelete(data) {
            const ids = data.ids || [];
            for (let i = 0; i < ids.length; i++) {
                this._handleLLMThreadDelete(ids[i]);
            }
        },

        _handleLLMThreadDelete(id) {
            const thread = this.env.models['mail.thread'].findFromIdentifyingData({
                id: id,
                model: 'llm.thread',
            });
            if (thread) {
                const llmChat = thread.llmChat;
                if (llmChat) {
                    const isActiveThread =
                        llmChat.activeThread && llmChat.activeThread.id === thread.id;
                    if (isActiveThread) {
                        const composer = llmChat.llmChatView && llmChat.llmChatView.composer;
                        if (composer && composer.isStreaming) {
                            composer._closeEventSource();
                        }
                    }
                    var filteredThreads = llmChat.threads.filter(function (t) {
                        return t.id !== thread.id;
                    });
                    const updatedData = {
                        threads: [['replace', filteredThreads]],
                    };
                    if (isActiveThread) {
                        updatedData.activeThread = clear();
                    }
                    llmChat.update(updatedData);
                }
                thread.delete();
            }
        },

        async _handleLLMThreadOpenInChatter(data) {
            const thread_id = data.thread_id;
            const model = data.model;
            const res_id = data.res_id;

            if (!thread_id) {
                return;
            }

            try {
                if (!this.env.messaging.llmChat) {
                    this.env.messaging.update({ llmChat: [['create', { isInitThreadHandled: false }]] });
                }

                let thread = this.env.models['mail.thread'].findFromIdentifyingData({
                    id: thread_id,
                    model: 'llm.thread',
                });

                if (!thread) {
                    const domain = [];
                    if (model && res_id) {
                        domain.push(['model', '=', model]);
                        domain.push(['res_id', '=', res_id]);
                    }
                    await this.env.messaging.llmChat.loadThreads([], domain);

                    thread = this.env.models['mail.thread'].findFromIdentifyingData({
                        id: thread_id,
                        model: 'llm.thread',
                    });
                }

                if (!thread) {
                    throw new Error('No se pudo cargar el hilo de conversación. Inténtelo de nuevo.');
                }

                await thread.openLLMThread({ focus: true });

                const llmChat = this.env.messaging.llmChat;
                if (llmChat && llmChat.llmChatView && llmChat.llmChatView.composer) {
                    await llmChat.llmChatView.composer.startGeneration();
                }
            } catch (error) {
                console.error('Error al abrir el hilo LLM en el chatter:', error);
                llmEnvUtils.llmNotify(this.env, {
                    title: 'Error al abrir el chat de IA',
                    message: error.message || 'Ha ocurrido un error inesperado',
                    type: 'danger',
                });
            }
        },
    });
});
