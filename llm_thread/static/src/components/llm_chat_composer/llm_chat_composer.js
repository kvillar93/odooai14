odoo.define('llm_thread/static/src/components/llm_chat_composer/llm_chat_composer.js', function (require) {
    'use strict';

    const AttachmentList = require('mail/static/src/components/attachment_list/attachment_list.js');
    const FileUploader = require('mail/static/src/components/file_uploader/file_uploader.js');
    const LLMChatComposerTextInput = require('llm_thread/static/src/components/llm_chat_composer_text_input/llm_chat_composer_text_input.js');
    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');

    const { Component } = owl;
    const { useRef, useState } = owl.hooks;

    class LLMChatComposer extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                const composer = this.env.models['mail.composer'].get(this.props.composerLocalId);
                return {
                    composerIsSendDisabled: composer && composer.isSendDisabled,
                    composerIsStreaming: composer && composer.isStreaming,
                    composerAttachments: composer ? composer.attachments.map(function (a) { return a.localId; }) : [],
                };
            }.bind(this));
            this.state = useState({
                isRecording: false,
                hasVoiceAPI: typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
            });
            this._mediaRecorder = null;
            this._audioChunks = [];
            this._fileUploaderRef = useRef('fileUploader');
        }

        get composerLocalId() {
            return this.props.composerLocalId;
        }

        get textInputSendShortcuts() {
            return this.props.textInputSendShortcuts;
        }

        get composer() {
            return this.env.models['mail.composer'].get(this.props.composerLocalId);
        }

        get isDisabled() {
            return this.composer && this.composer.isSendDisabled;
        }

        get isStreaming() {
            return this.composer && this.composer.isStreaming;
        }

        get messaging() {
            return this.env.messaging;
        }

        get newAttachmentExtraData() {
            return {
                composers: [['replace', this.composer]],
            };
        }

        _onClickSend() {
            if (this.isDisabled) {
                return;
            }
            this.composer.postUserMessageForLLM();
        }

        _onClickStop() {
            this.composer.stopLLMThreadLoop();
        }

        _onClickAddAttachment() {
            if (this._fileUploaderRef.comp) {
                this._fileUploaderRef.comp.openBrowserFileUploader();
            }
        }

        async onClickVoiceRecording() {
            if (!this.state.hasVoiceAPI) {
                return;
            }
            if (this.state.isRecording) {
                this._stopVoiceRecording();
            } else {
                await this._startVoiceRecording();
            }
        }

        async _startVoiceRecording() {
            const self = this;
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                self._audioChunks = [];
                let mimeType;
                if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
                    mimeType = 'audio/webm;codecs=opus';
                } else if (MediaRecorder.isTypeSupported('audio/webm')) {
                    mimeType = 'audio/webm';
                }
                self._mediaRecorder = mimeType
                    ? new MediaRecorder(stream, { mimeType: mimeType })
                    : new MediaRecorder(stream);
                self._mediaRecorder.ondataavailable = function (ev) {
                    if (ev.data && ev.data.size > 0) {
                        self._audioChunks.push(ev.data);
                    }
                };
                self._mediaRecorder.onstop = function () {
                    stream.getTracks().forEach(function (t) { t.stop(); });
                    const blob = new Blob(self._audioChunks, {
                        type: self._mediaRecorder.mimeType || 'audio/webm',
                    });
                    const ext = blob.type.includes('webm')
                        ? 'webm'
                        : blob.type.includes('ogg')
                            ? 'ogg'
                            : 'bin';
                    const file = new File(
                        [blob],
                        'nota-de-voz-' + Date.now() + '.' + ext,
                        { type: blob.type || 'audio/webm' }
                    );
                    if (self._fileUploaderRef.comp) {
                        self._fileUploaderRef.comp.uploadFiles([file]);
                    }
                    self.state.isRecording = false;
                    self._mediaRecorder = null;
                    self._audioChunks = [];
                };
                self._mediaRecorder.start();
                self.state.isRecording = true;
            } catch (e) {
                console.warn('Voice recording error', e);
                self.env.services.notification.notify({
                    message: self.env._t('No se pudo acceder al micrófono. Compruebe los permisos del navegador.'),
                    type: 'warning',
                });
            }
        }

        _stopVoiceRecording() {
            if (this._mediaRecorder && this.state.isRecording) {
                try {
                    this._mediaRecorder.stop();
                } catch (e) {
                    this.state.isRecording = false;
                }
            }
        }
    }

    Object.assign(LLMChatComposer, {
        props: {
            composerLocalId: String,
            textInputSendShortcuts: {
                type: Array,
                element: String,
            },
        },
        components: {
            AttachmentList: AttachmentList,
            FileUploader: FileUploader,
            LLMChatComposerTextInput: LLMChatComposerTextInput,
        },
        template: 'llm_thread.LLMChatComposer',
    });

    return LLMChatComposer;
});
