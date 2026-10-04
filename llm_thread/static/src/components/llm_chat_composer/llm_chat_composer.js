odoo.define('llm_thread/static/src/components/llm_chat_composer/llm_chat_composer.js', function (require) {
    'use strict';

    const AttachmentList = require('mail/static/src/components/attachment_list/attachment_list.js');
    const FileUploader = require('mail/static/src/components/file_uploader/file_uploader.js');
    const LLMChatComposerTextInput = require('llm_thread/static/src/components/llm_chat_composer_text_input/llm_chat_composer_text_input.js');
    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');

    const { dictationSupported, useDictation } = require('llm_thread/static/src/voice/llm_voice.js');

    const { Component } = owl;
    const { useRef } = owl.hooks;

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
            const self = this;
            this.dictationSupported = dictationSupported;
            this.dictation = useDictation({
                getThreadId: function () {
                    var thread = self.composer && self.composer.thread;
                    return thread && thread.model === 'llm.thread' ? thread.id : undefined;
                },
                onText: function (text) {
                    self._insertDictation(text);
                },
                onError: function (message) {
                    self.env.services.notification.notify({ message: message, type: 'warning' });
                },
            });
            this._fileUploaderRef = useRef('fileUploader');
            this._onBusUploadFile = this._onBusUploadFile.bind(this);
        }

        mounted() {
            this.env.messagingBus.on('llm-upload-file', this, this._onBusUploadFile);
        }

        willUnmount() {
            this.env.messagingBus.off('llm-upload-file', this);
        }

        _onBusUploadFile(payload) {
            if (!payload || !payload.file) {
                return;
            }
            var uploader = this._fileUploaderRef && this._fileUploaderRef.comp;
            if (uploader) {
                uploader.uploadFiles([payload.file]);
            } else {
                console.warn('[LLM Composer] FileUploader no disponible para subir:', payload.file.name);
            }
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

        get uploadId() {
            var thread = this.composer && this.composer.thread;
            return (thread && thread.id) || 0;
        }

        get uploadModel() {
            var thread = this.composer && this.composer.thread;
            return (thread && thread.model) || 'mail.compose.message';
        }

        _onClickSend() {
            if (this.isDisabled) {
                return;
            }
            this.composer.postUserMessageForLLM();
            var ta = this.el && this.el.querySelector('.o_ComposerTextInput_textarea');
            if (ta) {
                ta.value = '';
            }
        }

        _onClickStop() {
            this.composer.stopLLMThreadLoop();
        }

        _onClickAddAttachment() {
            if (this._fileUploaderRef.comp) {
                this._fileUploaderRef.comp.openBrowserFileUploader();
            }
        }

        _onDictationStart() {
            this.dictation.start();
        }

        _onDictationStop() {
            this.dictation.stop();
        }

        _onDictationCancel() {
            this.dictation.cancel();
        }

        /** Inserta el texto dictado en la posición del cursor, separado por un espacio. */
        _insertDictation(text) {
            var composer = this.composer;
            if (!composer) {
                return;
            }
            var before = (composer.textInputContent || '').slice(0, composer.textInputCursorStart || 0);
            var sep = before && !/\s$/.test(before) ? ' ' : '';
            composer.insertIntoTextInput(sep + text);
            composer.focus();
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
