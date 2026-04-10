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
            this._alive = false;
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
            var thread = this.props.record;
            var threadKey = thread ? (thread.localId || ('id:' + String(thread.id))) : '';
            if (threadKey !== this._lastThreadKey) {
                this._lastThreadKey = threadKey;
                this._lastMsgCount = -1;
                this._autoScrollUntil = Date.now() + 6000;
                var tv0 = this.props.threadView;
                if (tv0 && typeof tv0.update === 'function') {
                    tv0.update({ hasAutoScrollOnMessageReceived: true });
                }
                var self = this;
                [0, 50, 150, 300, 500, 800, 1200, 2000, 3500].forEach(function (ms) {
                    window.setTimeout(function () {
                        if (self._alive) { self._doScroll(); }
                    }, ms);
                });
            }
            var isStreaming = this.thread && this.thread.composer && this.thread.composer.isStreaming;
            if (isStreaming) {
                this._autoScrollUntil = Date.now() + 10000;
                this._scheduleScroll();
            }
            var tv = this.props.threadView;
            var count = tv && tv.nonEmptyMessages ? tv.nonEmptyMessages.length : 0;
            if (count !== this._lastMsgCount) {
                var self2 = this;
                [50, 200, 500].forEach(function (ms) {
                    window.setTimeout(function () {
                        if (self2._alive) { self2._doScroll(); }
                    }, ms);
                });
            }
            this._lastMsgCount = count;
        }

        mounted() {
            this._alive = true;
            this._lastThreadKey = null;
            this._lastMsgCount = -1;
            this._autoScrollUntil = Date.now() + 6000;
            this._onStreamUpdate = this._scheduleScroll.bind(this);
            this.env.messagingBus.on('llm-stream-update', this, this._onStreamUpdate);
            this._setupScrollResizeObserver();
            var self = this;
            [0, 100, 300, 600, 1200, 2500].forEach(function (ms) {
                window.setTimeout(function () {
                    if (self._alive) { self._doScroll(); }
                }, ms);
            });
        }

        willUnmount() {
            this._alive = false;
            this.env.messagingBus.off('llm-stream-update', this);
            if (this._scrollResizeObserver) {
                try {
                    this._scrollResizeObserver.disconnect();
                } catch (_e) {}
                this._scrollResizeObserver = null;
            }
        }

        _setupScrollResizeObserver() {
            var self = this;
            if (typeof ResizeObserver === 'undefined') {
                return;
            }
            this._scrollResizeObserver = new ResizeObserver(function () {
                if (!self._alive) {
                    return;
                }
                var streaming = self.thread && self.thread.composer && self.thread.composer.isStreaming;
                var inAutoWindow = Date.now() < (self._autoScrollUntil || 0);
                if (streaming || inAutoWindow) {
                    self._doScroll();
                }
            });
            window.requestAnimationFrame(function () {
                var el = self._scrollContentRef.el;
                if (el && self._scrollResizeObserver) {
                    self._scrollResizeObserver.observe(el);
                }
                var ml = self._messageListRef && self._messageListRef.el;
                if (ml && self._scrollResizeObserver) {
                    self._scrollResizeObserver.observe(ml);
                }
            });
        }

        _scheduleScroll() {
            var self = this;
            window.setTimeout(function () {
                if (self._alive) { self._doScroll(); }
            }, 0);
            window.setTimeout(function () {
                if (self._alive) { self._doScroll(); }
            }, 80);
        }

        _doScroll() {
            var self = this;

            // Mecanismo 1: scrollTop directo en todos los contenedores candidatos
            var seen = {};
            var targets = [];
            var add = function (el) {
                if (!el || el.nodeType !== 1 || seen[el]) {
                    return;
                }
                seen[el] = true;
                targets.push(el);
            };
            add(this._scrollContentRef.el);
            var root = this.el;
            if (root && root.closest) {
                var panel = root.closest('.o_llm_floating_panel');
                if (panel) {
                    var found = panel.querySelectorAll('.o_LLMChatThread_content');
                    for (var j = 0; j < found.length; j++) {
                        add(found[j]);
                    }
                }
            }
            var setInstant = function (node) {
                var max = node.scrollHeight - node.clientHeight;
                if (max > 0) {
                    node.scrollTop = max;
                }
            };
            for (var i = 0; i < targets.length; i++) {
                setInstant(targets[i]);
            }

            // Mecanismo 2: scrollIntoView en el sentinel (funciona aunque el
            // contenedor sea flex o block; el navegador calcula el scroll nativo)
            if (root) {
                var sentinel = root.querySelector('.o_LLMChatThread_scrollEnd');
                if (sentinel) {
                    try {
                        sentinel.scrollIntoView({ behavior: 'instant', block: 'end' });
                    } catch (_e) {
                        // Fallback para navegadores sin soporte de behavior:'instant'
                        try { sentinel.scrollIntoView(false); } catch (_e2) {}
                    }
                }
            }

            // Mecanismo 3: repetir en el siguiente frame para capturar reflows tardíos
            window.requestAnimationFrame(function () {
                if (!self._alive) { return; }
                for (var k = 0; k < targets.length; k++) {
                    setInstant(targets[k]);
                }
            });
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
