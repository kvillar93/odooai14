odoo.define('llm_thread/static/src/components/llm_chatter/llm_chatter.js', function (require) {
    'use strict';

    const Chatter = require('mail/static/src/components/chatter/chatter.js');
    const LLMChat = require('llm_thread/static/src/components/llm_chat/llm_chat.js');
    const openChatterAction = require('llm_thread/static/src/client_actions/open_chatter_action.js');

    Chatter.components = Object.assign({}, Chatter.components, { LLMChat: LLMChat });

    const originalUpdate = Chatter.prototype._update;
    Chatter.prototype._update = function () {
        originalUpdate.apply(this, arguments);
        if (!this._llmPendingOpenChecked && this.chatter && this.chatter.thread) {
            this._llmPendingOpenChecked = true;
            this._llmCheckPendingOpen();
        }
    };

    Chatter.prototype._llmCheckPendingOpen = async function () {
        const chatter = this.chatter;
        if (!chatter || !chatter.thread) {
            return;
        }

        const pending = openChatterAction.consumePendingOpenInChatter(
            chatter.thread.model,
            chatter.thread.id
        );

        if (!pending) {
            return;
        }

        try {
            const messaging = chatter.messaging;

            if (!messaging.llmChat) {
                messaging.update({ llmChat: [['create', { isInitThreadHandled: false }]] });
            }

            const Thread = messaging.models['mail.thread'];
            let thread = Thread.findFromIdentifyingData({
                id: pending.threadId,
                model: 'llm.thread',
            });

            if (!thread) {
                const domain = [
                    ['model', '=', pending.model],
                    ['res_id', '=', pending.resId],
                ];
                await messaging.llmChat.loadThreads([], domain);

                thread = Thread.findFromIdentifyingData({
                    id: pending.threadId,
                    model: 'llm.thread',
                });
            }

            if (!thread) {
                throw new Error('No se pudo cargar la conversación. Inténtelo de nuevo.');
            }

            await thread.openLLMThread({ focus: true });

            if (pending.autoGenerate) {
                const llmChat = messaging.llmChat;
                const composer = llmChat && llmChat.llmChatView && llmChat.llmChatView.composer;
                if (composer) {
                    await composer.startGeneration();
                }
            }
        } catch (error) {
            console.error('[LLM] Error al abrir el chat desde la acción pendiente:', error);
            chatter.messaging.env.services.notification.notify({
                title: 'Error al abrir el chat IA',
                message: error.message || 'Ha ocurrido un error inesperado',
                type: 'danger',
            });
        }
    };
});
