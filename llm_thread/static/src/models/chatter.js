odoo.define('llm_thread/static/src/models/chatter.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;

    registerFieldPatchModel('mail.chatter', 'llm_thread/static/src/models/chatter.js', {
        messaging: many2one('mail.messaging', {
            compute: '_computeMessaging',
        }),
        llmChatActiveThread: many2one('mail.thread', {
            related: 'messaging.llmChatActiveThread',
        }),
        is_chatting_with_llm: attr({
            compute: '_computeIsChattingWithLlm',
            dependencies: [
                'thread',
                'llmChatActiveThread',
            ],
        }),
    });

    registerInstancePatchModel('mail.chatter', 'llm_thread/static/src/models/chatter.js', {
        _computeMessaging() {
            return [['link', this.env.messaging]];
        },

        _computeIsChattingWithLlm() {
            const active = this.llmChatActiveThread;
            if (!active || !this.thread) {
                return false;
            }
            if (!active.relatedThreadModel || !active.relatedThreadId) {
                return false;
            }
            return (
                active.relatedThreadModel === this.thread.model &&
                active.relatedThreadId === this.thread.id
            );
        },

        async toggleLLMChat() {
            if (!this.thread) {
                return;
            }

            const messaging = this.env.messaging;
            let llmChat = messaging.llmChat;

            if (this.is_chatting_with_llm) {
                if (llmChat) {
                    llmChat.update({
                        activeThread: clear(),
                        relatedThreadModel: clear(),
                        relatedThreadId: clear(),
                    });
                }
            } else {
                try {
                    if (!llmChat) {
                        messaging.update({ llmChat: [['create', { isInitThreadHandled: false }]] });
                        llmChat = messaging.llmChat;
                    }

                    const thread = await llmChat.ensureThread({
                        relatedThreadModel: this.thread.model,
                        relatedThreadId: this.thread.id,
                    });

                    if (!thread) {
                        throw new Error('No se pudo preparar el hilo');
                    }

                    await thread.openLLMThread();
                } catch (error) {
                    llmEnvUtils.llmNotify(this.env, {
                        title: 'No se pudo iniciar el chat de IA',
                        message: error.message || 'Ha ocurrido un error',
                        type: 'danger',
                    });
                }
            }
        },
    });
});
