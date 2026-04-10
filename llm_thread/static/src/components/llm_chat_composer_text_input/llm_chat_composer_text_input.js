odoo.define('llm_thread/static/src/components/llm_chat_composer_text_input/llm_chat_composer_text_input.js', function (require) {
    'use strict';

    const ComposerTextInput = require('mail/static/src/components/composer_text_input/composer_text_input.js');

    class LLMChatComposerTextInput extends ComposerTextInput {
        /**
         * @override
         */
        get textareaPlaceholder() {
            if (this.composer && this.composer.thread && this.composer.thread.model === 'llm.thread') {
                const ph = this.composer.placeholderLLMChat;
                return ph ? this.env._t(ph) : this.env._t('Pregunte lo que quiera…');
            }
            return super.textareaPlaceholder;
        }

        /**
         * @override
         * @param {KeyboardEvent} ev
         */
        _onKeydownTextareaEnter(ev) {
            if (this.composer && this.composer.thread && this.composer.thread.model === 'llm.thread') {
                if (this.composer.hasSuggestions) {
                    ev.preventDefault();
                    return;
                }
                if (
                    this.props.sendShortcuts.includes('ctrl-enter') &&
                    !ev.altKey &&
                    ev.ctrlKey &&
                    !ev.metaKey &&
                    !ev.shiftKey
                ) {
                    this.composer.postUserMessageForLLM();
                    ev.preventDefault();
                    return;
                }
                if (
                    this.props.sendShortcuts.includes('enter') &&
                    !ev.altKey &&
                    !ev.ctrlKey &&
                    !ev.metaKey &&
                    !ev.shiftKey
                ) {
                    this.composer.postUserMessageForLLM();
                    ev.preventDefault();
                    return;
                }
                if (
                    this.props.sendShortcuts.includes('meta-enter') &&
                    !ev.altKey &&
                    !ev.ctrlKey &&
                    ev.metaKey &&
                    !ev.shiftKey
                ) {
                    this.composer.postUserMessageForLLM();
                    ev.preventDefault();
                    return;
                }
                return;
            }
            super._onKeydownTextareaEnter(ev);
        }
    }

    Object.assign(LLMChatComposerTextInput, {
        components: ComposerTextInput.components,
        defaultProps: ComposerTextInput.defaultProps,
        props: ComposerTextInput.props,
        template: 'mail.ComposerTextInput',
    });

    return LLMChatComposerTextInput;
});
