odoo.define('llm_experience/static/src/components/llm_context_meter/llm_context_meter.js', function (require) {
    'use strict';

    const { Component } = owl;
    const {
        onMounted,
        onPatched,
        onWillStart,
        onWillUnmount,
        onWillUpdateProps,
        useRef,
        useState,
    } = owl.hooks;

    /** Radio del arco del gauge (viewBox 40x40, centro 20,20) */
    const GAUGE_R = 16;
    const REFRESH_THROTTLE_MS = 800;

    /** Barras encendidas por nivel (0 = rayo de instantáneo). */
    const EFFORT_BARS = { instant: 0, low: 1, medium: 2, high: 3, xhigh: 4 };

    function formatTokens(value) {
        const n = Number(value) || 0;
        if (n >= 1000000) {
            return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1) + 'M';
        }
        if (n >= 1000) {
            return (n / 1000).toFixed(n >= 100000 ? 0 : 1) + 'k';
        }
        return String(n);
    }

    class LLMContextMeter extends Component {
        constructor() {
            super(...arguments);
            this.rootRef = useRef('root');
            this.effortTriggerRef = useRef('effortTrigger');
            this.ringTriggerRef = useRef('ringTrigger');
            this.popoverRef = useRef('popover');
            this.state = useState({
                data: null,
                loaded: false,
                popover: null, // "effort" | "context" | null
                busy: false,
                confirmReset: false,
                notice: '',
            });
            this._lastFetch = 0;
            this._pendingFetch = null;
            this._layoutListeners = false;
            this._onRefreshEvent = this._onRefreshEvent.bind(this);
            this._onDocClick = this._onDocClick.bind(this);
            this._onLayout = this._onLayout.bind(this);
            window.addEventListener('llm-experience-refresh-meter', this._onRefreshEvent);

            const self = this;
            onMounted(function () {
                document.addEventListener('click', self._onDocClick);
            });
            onWillUnmount(function () {
                window.removeEventListener('llm-experience-refresh-meter', self._onRefreshEvent);
                document.removeEventListener('click', self._onDocClick);
                self._toggleLayoutListeners(false);
                clearTimeout(self._pendingFetch);
            });
            onWillUpdateProps(function (next) {
                if (next.threadId !== self.props.threadId) {
                    self.closePopover();
                    self.fetch(next.threadId);
                }
            });
            onWillStart(function () {
                return self.fetch();
            });
            onPatched(function () {
                if (self.state.popover) {
                    requestAnimationFrame(function () {
                        self._positionPopover();
                    });
                    self._toggleLayoutListeners(true);
                } else {
                    self._toggleLayoutListeners(false);
                }
            });
        }

        // ------------------------------------------------------------------
        // Datos
        // ------------------------------------------------------------------

        async fetch(threadId) {
            const tid = threadId || this.props.threadId;
            if (!tid) {
                this.state.data = null;
                this.state.loaded = true;
                return;
            }
            this._lastFetch = Date.now();
            try {
                const data = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'experience_meter_rpc',
                    args: [tid],
                });
                this._applyPayload(data);
            } catch (e) {
                this.state.data = null;
            }
            this.state.loaded = true;
        }

        _applyPayload(data) {
            if (data && !data.error) {
                this.state.data = data;
            }
        }

        _onRefreshEvent() {
            const self = this;
            const wait = REFRESH_THROTTLE_MS - (Date.now() - this._lastFetch);
            clearTimeout(this._pendingFetch);
            if (wait <= 0) {
                this.fetch();
            } else {
                this._pendingFetch = setTimeout(function () {
                    self.fetch();
                }, wait);
            }
        }

        async _call(method, extraArgs) {
            this.state.busy = true;
            this.state.notice = '';
            try {
                const data = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: method,
                    args: [this.props.threadId].concat(extraArgs || []),
                });
                this._applyPayload(data);
                if (data && data.notice) {
                    this.state.notice = data.notice;
                }
                if (data && data.note_message) {
                    // El chat flotante no usa los modelos de mail: lo avisamos por evento.
                    window.dispatchEvent(new CustomEvent('llm-thread-note', {
                        detail: { threadId: this.props.threadId, message: data.note_message },
                    }));
                    this._insertMessage(data.note_message);
                }
                return data;
            } catch (e) {
                this.state.notice = (e && e.message && (e.message.data ? e.message.data.message : e.message)) || 'Error';
            } finally {
                this.state.busy = false;
            }
        }

        _insertMessage(messageData) {
            try {
                const Message = this.env.models['mail.message'];
                Message.insert(Message.convertData(messageData));
                if (this.env.messagingBus) {
                    this.env.messagingBus.trigger('llm-stream-update');
                }
            } catch (e) {
                console.warn('llm_experience: no se pudo mostrar la nota en el chat', e);
            }
        }

        // ------------------------------------------------------------------
        // Getters de vista
        // ------------------------------------------------------------------

        get data() {
            return this.state.data;
        }

        get selectorEnabled() {
            return !!this.data && this.data.work_mode_selector_enabled !== false;
        }

        get effortOptions() {
            return (this.data && this.data.reasoning_options) || [];
        }

        get currentEffort() {
            const value = (this.data && this.data.reasoning_effort) || 'medium';
            const found = this.effortOptions.find(function (o) {
                return o.value === value;
            });
            return found || { value: value, label: value };
        }

        /** Glifo de nivel: rayo (instantáneo) o 4 barras con n encendidas. */
        effortGlyph(value) {
            const lit = value in EFFORT_BARS ? EFFORT_BARS[value] : 2;
            return {
                bolt: lit === 0,
                bars: [1, 2, 3, 4].map(function (n) {
                    return {
                        n: n,
                        cls: 'o_llm_exp__bar o_llm_exp__bar--' + n + (n <= lit ? ' o_llm_exp__bar--on' : ''),
                    };
                }),
            };
        }

        get pct() {
            const d = this.data;
            if (!d || !d.limit) {
                return 0;
            }
            return Math.min(100, Math.round((100 * (d.live || 0)) / d.limit));
        }

        get compactionPct() {
            return Math.round(((this.data && this.data.compaction_ratio) || 0.85) * 100);
        }

        get stateSuffix() {
            const s = this.data && this.data.state;
            return s === 'critical' || s === 'warning' ? s : 'normal';
        }

        get gaugeDashArray() {
            return String(2 * Math.PI * GAUGE_R);
        }

        get gaugeDashOffset() {
            return 2 * Math.PI * GAUGE_R * (1 - this.pct / 100);
        }

        get ringTitle() {
            const d = this.data;
            if (!d) {
                return '';
            }
            return 'Contexto: ' + formatTokens(d.live) + ' / ' + formatTokens(d.limit) + ' tokens (' + this.pct + ' %)';
        }

        get compactionStatus() {
            const d = this.data;
            if (!d) {
                return '';
            }
            if (d.needs_compaction || d.state === 'critical') {
                return 'Se resumirá automáticamente antes de la próxima respuesta.';
            }
            return 'Se resumirá automáticamente al ' + this.compactionPct + ' % · faltan ~' +
                formatTokens(d.tokens_until_compaction) + ' tokens.';
        }

        get breakdown() {
            var data = this.data;
            return ((data && data.breakdown) || []).map(function (seg) {
                return Object.assign({}, seg, {
                    width: Math.max(1.5, seg.ratio * 100).toFixed(1) + '%',
                    tokensLabel: formatTokens(seg.tokens),
                });
            });
        }

        get costLabel() {
            const cost = Number(this.data && this.data.cost_usd_total);
            if (Number.isNaN(cost)) {
                return '';
            }
            return cost.toFixed(cost >= 1 ? 2 : 4) + ' ' + (this.data.cost_currency || 'USD');
        }

        get lastCompactionLabel() {
            const raw = this.data && this.data.last_compaction;
            if (!raw) {
                return '';
            }
            const date = new Date(raw.replace(' ', 'T') + 'Z');
            return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
        }

        fmt(value) {
            return formatTokens(value);
        }

        // ------------------------------------------------------------------
        // Popovers
        // ------------------------------------------------------------------

        toggleEffortMenu(ev) {
            ev.stopPropagation();
            this._togglePopover('effort');
        }

        toggleContextCard(ev) {
            ev.stopPropagation();
            this._togglePopover('context');
            if (this.state.popover === 'context') {
                this.fetch();
            }
        }

        _togglePopover(name) {
            this.state.confirmReset = false;
            this.state.notice = '';
            this.state.popover = this.state.popover === name ? null : name;
        }

        closePopover() {
            this.state.popover = null;
            this.state.confirmReset = false;
        }

        _onDocClick(ev) {
            if (!this.state.popover) {
                return;
            }
            const root = this.rootRef.el;
            const popover = this.popoverRef.el;
            if ((root && root.contains(ev.target)) || (popover && popover.contains(ev.target))) {
                return;
            }
            this.closePopover();
        }

        _toggleLayoutListeners(on) {
            if (on === this._layoutListeners) {
                return;
            }
            this._layoutListeners = on;
            const method = on ? 'addEventListener' : 'removeEventListener';
            window[method]('resize', this._onLayout);
            window[method]('scroll', this._onLayout, true);
        }

        _onLayout() {
            if (this.state.popover) {
                this._positionPopover();
            }
        }

        /** Coordenadas de viewport: evita recortes por overflow de ancestros. */
        _positionPopover() {
            const popover = this.popoverRef.el;
            const trigger = this.state.popover === 'effort' ? this.effortTriggerRef.el : this.ringTriggerRef.el;
            if (!popover || !trigger) {
                return;
            }
            const rect = trigger.getBoundingClientRect();
            const pad = 8;
            const gap = 6;
            const width = popover.offsetWidth;
            const height = popover.offsetHeight;
            let left = Math.min(rect.left, window.innerWidth - pad - width);
            left = Math.max(pad, left);
            let top = rect.top - height - gap;
            if (top < pad) {
                top = Math.min(rect.bottom + gap, window.innerHeight - pad - height);
            }
            popover.style.position = 'fixed';
            popover.style.left = Math.round(left) + 'px';
            popover.style.top = Math.round(Math.max(pad, top)) + 'px';
            popover.style.zIndex = '1080';
        }

        // ------------------------------------------------------------------
        // Acciones
        // ------------------------------------------------------------------

        async onPickEffort(ev) {
            ev.stopPropagation();
            const value = ev.currentTarget.dataset.value;
            this.closePopover();
            if (value && (!this.data || value !== this.data.reasoning_effort)) {
                await this._call('experience_set_reasoning_effort_rpc', [value]);
            }
        }

        async onToggleResearch(ev) {
            ev.stopPropagation();
            await this._call('experience_set_deep_research_rpc', [!(this.data && this.data.deep_research)]);
        }

        async onCompactNow(ev) {
            ev.stopPropagation();
            await this._call('experience_compact_now_rpc', []);
        }

        async onResetContext(ev) {
            ev.stopPropagation();
            if (!this.state.confirmReset) {
                this.state.confirmReset = true;
                return;
            }
            this.state.confirmReset = false;
            await this._call('experience_reset_context_rpc', []);
        }
    }

    LLMContextMeter.template = 'llm_experience.LLMContextMeter';
    LLMContextMeter.props = {
        threadId: { type: Number, optional: true },
    };

    // Disponible para el chat flotante de llm_thread (no depende de llm_experience).
    require('llm_thread/static/src/js/llm_ui_utils.js').extraComponents.LLMContextMeter = LLMContextMeter;

    return LLMContextMeter;
});
