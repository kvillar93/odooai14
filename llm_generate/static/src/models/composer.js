odoo.define('llm_generate/static/src/models/composer.js', function (require) {
    'use strict';

    const { registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    registerInstancePatchModel('mail.composer', 'llm_generate/static/src/models/composer.js', {
        postUserGenerationMessageForLLM: function (inputs, attachments) {
            attachments = attachments || [];
            const thread = this.thread;

            if (!thread || !thread.id) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('El hilo no está disponible.'),
                    type: 'danger',
                });
                return;
            }

            const messageBody = inputs.prompt || 'Content Generation Request';
            if (!messageBody) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('Escriba un mensaje.'),
                    type: 'danger',
                });
                return;
            }

            if (!thread.llmModel || !thread.llmModel.isMediaGenerationModel) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('El modelo seleccionado no está configurado para generación.'),
                    type: 'danger',
                });
                return;
            }

            this._reset();

            const self = this;
            const attachmentIds = attachments.map(function (att) { return att.id; });

            this.async(function () {
                return this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'message_post',
                    args: [thread.id],
                    kwargs: {
                        body: messageBody,
                        body_json: inputs,
                        llm_role: 'user',
                        attachment_ids: attachmentIds,
                    },
                });
            }.bind(this)).then(function () {
                self._startGeneration(thread.id);
            }).catch(function (error) {
                console.error('Error al publicar mensaje de generación:', error);
                llmEnvUtils.llmNotify(self.env, {
                    message: self.env._t('No se pudo publicar el mensaje de generación: ') + String(error),
                    type: 'danger',
                    sticky: true,
                });
            });
        },

        _startGeneration: function (threadId) {
            const self = this;
            try {
                const url = '/llm/thread/generate?thread_id=' + threadId;
                const eventSource = new EventSource(url);
                this.update({ eventSource: eventSource });

                eventSource.onmessage = async function (event) {
                    try {
                        const data = JSON.parse(event.data);

                        switch (data.type) {
                            case 'message_create':
                                self._handleMessageCreate(data.message);
                                break;
                            case 'message_chunk':
                                self._handleMessageUpdate(data.message);
                                break;
                            case 'message_update':
                                self._handleMessageUpdate(data.message);
                                break;
                            case 'error':
                                self._closeEventSource();
                                llmEnvUtils.llmNotify(self.env, {
                                    message: data.error,
                                    type: 'danger',
                                    sticky: true,
                                });
                                break;
                            case 'done': {
                                const messaging = self.env.messaging;
                                const llmChat = messaging && messaging.llmChat;
                                const sameThread = llmChat && llmChat.activeThread && self.thread &&
                                    llmChat.activeThread.id === self.thread.id;
                                if (!sameThread && self.thread) {
                                    const label = self.thread.name || ('#' + self.thread.id);
                                    llmEnvUtils.llmNotify(self.env, {
                                        message: self.env._t('Generación completada para ') + label,
                                        type: 'success',
                                    });
                                }
                                self._closeEventSource();
                                break;
                            }
                            default:
                                console.warn('Tipo de evento de generación desconocido:', data.type);
                        }
                    } catch (parseError) {
                        console.error('Error al analizar evento de generación:', parseError);
                        llmEnvUtils.llmNotify(self.env, {
                            message: self.env._t('Error al procesar la respuesta del servidor.'),
                            type: 'danger',
                        });
                    }
                };

                eventSource.onerror = function () {
                    console.error('EventSource falló');
                    llmEnvUtils.llmNotify(self.env, {
                        message: self.env._t('Se perdió la conexión con el servidor. Inténtelo de nuevo.'),
                        type: 'danger',
                        sticky: true,
                    });
                    self._closeEventSource();
                };
            } catch (error) {
                console.error('Error al iniciar generación:', error);
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('No se pudo iniciar la generación: ') + String(error),
                    type: 'danger',
                    sticky: true,
                });
            } finally {
                if (this.composerViews) {
                    for (let i = 0; i < this.composerViews.length; i++) {
                        this.composerViews[i].update({ doFocus: true });
                    }
                }
            }
        },
    });
});
