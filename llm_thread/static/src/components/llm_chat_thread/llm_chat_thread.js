odoo.define('llm_thread/static/src/components/llm_chat_thread/llm_chat_thread.js', function (require) {
    'use strict';

    const MessageList = require('mail/static/src/components/message_list/message_list.js');
    const LLMChatThreadHeader = require('llm_thread/static/src/components/llm_chat_thread_header/llm_chat_thread_header.js');
    const LLMChatComposer = require('llm_thread/static/src/components/llm_chat_composer/llm_chat_composer.js');
    const LLMStreamingIndicator = require('llm_thread/static/src/components/llm_streaming_indicator/llm_streaming_indicator.js');
    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');

    const { Component } = owl;
    const { useRef } = owl.hooks;

    const ANALYZING_LABEL = 'Analizando';

    class LLMChatThread extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                const threadView = this.props.threadView;
                const thread = this.props.record;
                const tc = threadView && threadView.threadCache;
                const composer = thread && thread.composer;
                return {
                    threadView,
                    thread,
                    threadCacheLoading: tc && tc.isLoading,
                    nonEmptyCount: threadView && threadView.nonEmptyMessages
                        ? threadView.nonEmptyMessages.length
                        : 0,
                    composerStreaming: composer && composer.isStreaming,
                };
            }.bind(this));
            this._scrollContentRef = useRef('scrollContent');
            this._messageListRef = useRef('messageList');
            this._llmScrollRaf = null;
            this.getScrollableElement = function () {
                return this._scrollContentRef.el;
            }.bind(this);
            this.starterPrompts = [
                {
                    icon: 'fa-lightbulb-o',
                    label: 'Ventajas de CRM y ventas en Odoo',
                    text: 'Resume en viñetas las ventajas de usar CRM y ventas integrados en Odoo para una pyme.',
                },
                {
                    icon: 'fa-table',
                    label: 'Tabla de ejemplo en Markdown',
                    text: 'Genera una tabla Markdown de ejemplo con columnas Cliente, Pedido, Total y Estado.',
                },
                {
                    icon: 'fa-line-chart',
                    label: 'Interpretar un informe de facturación',
                    text: 'Explícame paso a paso cómo interpretar un informe de facturación mensual en Odoo.',
                },
                {
                    icon: 'fa-code',
                    label: 'Consulta SQL de solo lectura',
                    text: 'Escribe un SELECT de solo lectura que liste las últimas 10 facturas publicadas con importe y partner.',
                },
            ];
        }

        patched() {
            if (this.thread && this.thread.composer && this.thread.composer.isStreaming) {
                this._scheduleScrollToEnd();
            }
        }

        mounted() {
            this._scheduleScrollToEnd();
        }

        _scheduleScrollToEnd() {
            const self = this;
            if (self._llmScrollRaf) {
                return;
            }
            self._llmScrollRaf = window.requestAnimationFrame(function () {
                self._llmScrollRaf = null;
                self._scrollToEnd();
            });
        }

        _scrollToEnd() {
            const el = this._scrollContentRef.el;
            if (!el) {
                return;
            }
            const setEnd = function (node) {
                if (!node) {
                    return;
                }
                node.scrollTop = node.scrollHeight - node.clientHeight;
            };
            setEnd(el);
            const ml = this._messageListRef.el;
            if (ml) {
                setEnd(ml);
            }
        }

        get threadView() {
            return this.props.threadView;
        }

        get thread() {
            return this.props.record;
        }

        get analyzingChars() {
            return [...ANALYZING_LABEL];
        }

        get showConversationStarters() {
            const tv = this.threadView;
            const tc = tv && tv.threadCache;
            if (!tc || tc.isLoading) {
                return false;
            }
            return tv.nonEmptyMessages.length === 0;
        }

        /** Orden de la lista de mensajes (ascendente para chat). */
        get messageListOrder() {
            return 'asc';
        }

        /** Atajos de envío para el compositor (desde thread_view de mail). */
        get textInputSendShortcuts() {
            const tv = this.threadView;
            if (tv && tv.textInputSendShortcuts) {
                return tv.textInputSendShortcuts;
            }
            return ['enter'];
        }

        /**
         * @param {MouseEvent} ev
         */
        _onClickStarter(ev) {
            const idx = parseInt(ev.currentTarget.dataset.index, 10);
            const st = this.starterPrompts[idx];
            if (!st) {
                return;
            }
            const text = st.text;
            const composer = this.thread && this.thread.composer;
            if (!composer) {
                return;
            }
            composer.update({
                textInputContent: text,
                isLastStateChangeProgrammatic: false,
            });
            const self = this;
            window.setTimeout(function () {
                const ta = document.querySelector('.o_LLMChatComposer textarea') ||
                    document.querySelector('.o_LLMChatComposer .o_ComposerTextInput_textarea');
                if (ta && typeof ta.focus === 'function') {
                    ta.focus();
                    if (typeof ta.setSelectionRange === 'function') {
                        const n = text.length;
                        ta.setSelectionRange(n, n);
                    }
                }
            }, 0);
        }
    }

    var _origOnScrollThrottled = MessageList.prototype._onScrollThrottled;
    MessageList.prototype._onScrollThrottled = function () {
        var vals = this._lastRenderedValues && this._lastRenderedValues();
        if (!vals) {
            return;
        }
        return _origOnScrollThrottled.apply(this, arguments);
    };

    Object.assign(LLMChatThread, {
        props: {
            record: Object,
            threadView: Object,
        },
        components: {
            LLMChatThreadHeader: LLMChatThreadHeader,
            MessageList: MessageList,
            LLMChatComposer: LLMChatComposer,
            LLMStreamingIndicator: LLMStreamingIndicator,
        },
        template: 'llm_thread.LLMChatThread',
    });

    return LLMChatThread;
});
