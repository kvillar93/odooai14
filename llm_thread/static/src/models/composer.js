odoo.define('llm_thread/static/src/models/composer.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

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
            const thread = llmChat && llmChat.activeThread;

            if (!thread || thread.model !== 'llm.thread') {
                console.warn('No active LLM thread for generation');
                return;
            }

            const usePost = attachmentIds && attachmentIds.length > 0;
            const baseUrl = '/llm/thread/generate?thread_id=' + thread.id;

            try {
                if (usePost) {
                    const csrfToken = (typeof odoo !== 'undefined' && odoo.csrf_token) || '';
                    const url = baseUrl + '&csrf_token=' + encodeURIComponent(csrfToken);
                    const response = await fetch(url, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify({
                            message: messageBody || '',
                            attachment_ids: attachmentIds,
                        }),
                    });
                    if (!response.ok) {
                        throw new Error(response.statusText || 'POST fallido');
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
            } catch (error) {
                console.error('Error sending LLM message:', error);
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('No se pudo enviar el mensaje.'),
                    type: 'danger',
                });
                this._closeEventSource();
            } finally {
                if (this.thread && this.thread.composer) {
                    this.thread.composer.update({ hasFocus: true });
                }
            }
        },

        async postUserMessageForLLM() {
            const thread = this.thread;
            const messageBody = this.textInputContent.trim();
            const attachmentIds = this.attachments.map(function (a) { return a.id; });
            if ((!messageBody && !attachmentIds.length) || !thread) {
                llmEnvUtils.llmNotify(this.env, {
                    message: this.env._t('Escriba un mensaje o adjunte un archivo.'),
                    type: 'danger',
                });
                return;
            }

            this._reset();
            await this.startGeneration(messageBody, attachmentIds);
        },

        _closeEventSource() {
            if (this.eventSource && this.eventSource.close) {
                this.eventSource.close();
            }
            this.update({ eventSource: null });
        },

        _handleMessageCreate(message) {
            const Message = this.env.models['mail.message'];
            return Message.insert(Message.convertData(message));
        },

        _handleMessageUpdate(message) {
            const Message = this.env.models['mail.message'];
            const result = Message.findFromIdentifyingData({
                id: message.id,
            });
            if (result) {
                result.update(Message.convertData(message));
            }
            return result;
        },
    });
});
