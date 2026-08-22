odoo.define('llm_thread/static/src/models/composer.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');
    const webCore = require('web.core');

    const attr = ModelField.attr;

    registerFieldPatchModel('mail.composer', 'llm_thread/static/src/models/composer.js', {
        placeholderLLMChat: attr({
            default: 'Ask anything...',
        }),
        isSendDisabled: attr({
            compute: '_computeIsSendDisabled',
            dependencies: [
                'thread',
                'textInputContent',
                'attachments',
                'hasUploadingAttachment',
                'eventSource',
                'canPostMessage',
            ],
            default: true,
        }),
        eventSource: attr({
            default: null,
        }),
        isStreaming: attr({
            compute: '_computeIsStreaming',
            dependencies: ['eventSource'],
        }),
    });

    registerInstancePatchModel('mail.composer', 'llm_thread/static/src/models/composer.js', {
        _computeIsSendDisabled() {
            if (this.thread && this.thread.model === 'llm.thread') {
                const hasText = Boolean(this.textInputContent && this.textInputContent.trim());
                const hasFiles = this.attachments.length > 0;
                if (!hasText && !hasFiles) {
                    return true;
                }
                return this.hasUploadingAttachment || Boolean(this.eventSource);
            }
            return !this.canPostMessage;
        },

        _computeIsStreaming() {
            return this.eventSource !== null;
        },

        stopLLMThreadLoop() {
            this._closeEventSource();
        },

        _dispatchStreamEvent(data) {
            const messaging = this.env.messaging;
            switch (data.type) {
                case 'message_create':
                    this._handleMessageCreate(data.message);
                    break;
                case 'message_chunk':
                    this._handleMessageUpdate(data.message);
                    break;
                case 'message_update':
                    this._handleMessageUpdate(data.message);
                    break;
                case 'tool_start':
                    if (messaging.llmChat) {
                        messaging.llmChat.update({
                            llmAnalyzingToolName: data.tool_name || '…',
                        });
                    }
                    break;
                case 'tool_end':
                    if (messaging.llmChat) {
                        messaging.llmChat.update({ llmAnalyzingToolName: clear() });
                    }
                    break;
                case 'error':
                    this._closeEventSource();
                    llmEnvUtils.llmNotify(this.env, { message: data.error, type: 'danger' });
                    break;
                case 'thread_name_update': {
                    // El nombre se envía dentro de la transacción del generador,
                    // antes del commit, para que el cliente lo vea inmediatamente
                    // sin tener que esperar al refreshThread del evento 'done'.
                    if (data.thread_id && data.name) {
                        const Thread = this.env.models['mail.thread'];
                        const threadRecord = Thread.findFromIdentifyingData({
                            id: data.thread_id,
                            model: 'llm.thread',
                        });
                        if (threadRecord) {
                            threadRecord.update({ name: data.name });
                        }
                    }
                    break;
                }
                case 'done': {
                    const llmChat = messaging.llmChat;
                    const sameThread = llmChat && llmChat.activeThread && this.thread &&
                        llmChat.activeThread.id === this.thread.id;
                    if (!sameThread && this.thread) {
                        llmEnvUtils.llmNotify(this.env, {
                            message: this.env._t('Generación completada para ') + this.thread.displayName,
                            type: 'success',
                        });
                    }
                    if (llmChat && this.thread && this.thread.id) {
                        llmChat.refreshThread(this.thread.id).catch(function () {});
                    }
                    this._closeEventSource();
                    break;
                }
            }
        },

        async _consumeSSEFromResponse(response) {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const readResult = await reader.read();
                if (readResult.done) {
                    break;
                }
                buffer += decoder.decode(readResult.value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop() || '';
                for (let i = 0; i < parts.length; i++) {
                    const line = parts[i].trim();
                    if (line.indexOf('data: ') !== 0) {
                        continue;
                    }
                    const jsonStr = line.slice(6);
                    if (jsonStr === '[DONE]') {
                        continue;
                    }
                    try {
                        const data = JSON.parse(jsonStr);
                        this._dispatchStreamEvent(data);
                    } catch (e) {
                        console.warn('SSE parse error', e, jsonStr);
                    }
                }
            }
        },

        async startGeneration(messageBody, attachmentIds) {
            messageBody = messageBody === undefined ? null : messageBody;
            attachmentIds = attachmentIds || [];
            const llmChat = this.env.messaging.llmChat;
            var thread = this.thread;
            if (!thread || thread.model !== 'llm.thread') {
                thread = llmChat && llmChat.activeThread;
            }

            if (!thread || thread.model !== 'llm.thread') {
                console.warn('No active LLM thread for generation');
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('No hay un chat activo para enviar el mensaje.'),
                    type: 'danger',
                });
                return false;
            }

            // Los mensajes largos no caben en GET (Werkzeug/Nginx cortan ~8 KB
            // y responden HTML en vez de SSE). POST si hay adjuntos o el
            // cuerpo url-encoded supera ~4 KB.
            const URL_SAFE_LIMIT = 4000;
            const encodedLen = messageBody
                ? encodeURIComponent(messageBody).length
                : 0;
            const usePost =
                (attachmentIds && attachmentIds.length > 0) ||
                encodedLen > URL_SAFE_LIMIT;
            const baseUrl = '/llm/thread/generate?thread_id=' + thread.id;

            try {
                if (usePost) {
                    // Odoo 14 trata application/json como JsonRequest y rechaza
                    // esta ruta type=http. Hay que enviar form-urlencoded.
                    var csrfToken = (webCore && webCore.csrf_token) ||
                        (typeof odoo !== 'undefined' && odoo.csrf_token) || '';
                    var formBody = new URLSearchParams();
                    formBody.append('csrf_token', csrfToken);
                    formBody.append('message', messageBody || '');
                    formBody.append('attachment_ids', JSON.stringify(attachmentIds));
                    var url = baseUrl + '&csrf_token=' + encodeURIComponent(csrfToken);
                    var response = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        },
                        credentials: 'include',
                        body: formBody.toString(),
                    });
                    if (!response.ok) {
                        var detail = response.statusText || '';
                        try {
                            var errBody = await response.text();
                            if (errBody) {
                                detail = (detail ? detail + ': ' : '') + errBody.slice(0, 400);
                            }
                        } catch (readErr) {
                            /* ignorar */
                        }
                        throw new Error(detail || 'POST fallido');
                    }
                    var ctype = (response.headers.get('Content-Type') || '').toLowerCase();
                    if (ctype && ctype.indexOf('text/event-stream') === -1 && ctype.indexOf('text/html') !== -1) {
                        var htmlBody = await response.text();
                        throw new Error(htmlBody.slice(0, 300) || 'Respuesta HTML inesperada');
                    }
                    this.update({ eventSource: { streamReader: true } });
                    await this._consumeSSEFromResponse(response);
                    this.update({ eventSource: null });
                } else {
                    let url = baseUrl;
                    if (messageBody) {
                        url += '&message=' + encodeURIComponent(messageBody);
                    }
                    const eventSource = new EventSource(url);
                    this.update({ eventSource: eventSource });

                    const self = this;
                    eventSource.onmessage = async function (event) {
                        const data = JSON.parse(event.data);
                        self._dispatchStreamEvent(data);
                    };
                    eventSource.onerror = function () {
                        console.error('EventSource failed');
                        llmEnvUtils.llmNotify(self.env, {
                            message: self.env._t('Ocurrió un error desconocido'),
                            type: 'danger',
                        });
                        self._closeEventSource();
                    };
                }
                return true;
            } catch (error) {
                console.error('Error sending LLM message:', error);
                var errMsg = (error && error.message) || this.env._t('No se pudo enviar el mensaje.');
                llmEnvUtils.llmNotify(this.env, {
                    message: errMsg,
                    type: 'danger',
                });
                this._closeEventSource();
                return false;
            } finally {
                if (this.thread && this.thread.composer) {
                    this.thread.composer.update({ hasFocus: true });
                }
            }
        },

        async postUserMessageForLLM() {
            var thread = this.thread;
            var messageBody = this.textInputContent.trim();
            var attachmentIds = this.attachments
                .map(function (a) { return parseInt(a.id, 10); })
                .filter(function (id) { return id > 0 && !isNaN(id); });

            if ((!messageBody && !attachmentIds.length) || !thread) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('Escriba un mensaje o adjunte un archivo.'),
                    type: 'danger',
                });
                return;
            }

            if (this.hasUploadingAttachment) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('Espere a que los archivos terminen de subir.'),
                    type: 'warning',
                });
                return;
            }

            this.update({
                isLastStateChangeProgrammatic: true,
                textInputContent: '',
                textInputCursorEnd: 0,
                textInputCursorStart: 0,
            });
            this.env.messagingBus.trigger('llm-stream-update');

            var sent = await this.startGeneration(messageBody, attachmentIds);
            if (sent) {
                this.update({
                    attachments: [['unlink-all']],
                    mentionedChannels: [['unlink-all']],
                    mentionedPartners: [['unlink-all']],
                    subjectContent: '',
                });
            }
        },

        _closeEventSource() {
            if (this.eventSource && this.eventSource.close) {
                this.eventSource.close();
            }
            this.update({ eventSource: null });
        },

        _handleMessageCreate(message) {
            const Message = this.env.models['mail.message'];
            var result = Message.insert(Message.convertData(message));
            this.env.messagingBus.trigger('llm-stream-update');
            return result;
        },

        _handleMessageUpdate(message) {
            const Message = this.env.models['mail.message'];
            const result = Message.findFromIdentifyingData({
                id: message.id,
            });
            if (result) {
                result.update(Message.convertData(message));
            }
            this.env.messagingBus.trigger('llm-stream-update');
            return result;
        },
    });
});
