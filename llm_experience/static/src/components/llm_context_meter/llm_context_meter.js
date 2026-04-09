/** @odoo-module **/

import {
  Component,
  onMounted,
  onPatched,
  onWillStart,
  onWillUnmount,
  onWillUpdateProps,
  useRef,
  useState,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registerMessagingComponent } from "@mail/utils/messaging_component";

/** Radio del arco del gauge (viewBox 40x40, centro 20,20) */
const GAUGE_R = 16;

const MODES = [
  {
    value: "normal",
    label: "Respuesta normal",
    abbr: "RN",
    icon: "fa-comments",
  },
  {
    value: "deep_thinking",
    label: "Pensamiento profundo",
    abbr: "PP",
    icon: "fa-lightbulb-o",
  },
  {
    value: "deep_research",
    label: "Investigación profunda",
    abbr: "IP",
    icon: "fa-search",
  },
];

export class LLMContextMeter extends Component {
  setup() {
    this.orm = useService("orm");
    this.rootRef = useRef("root");
    this.triggerRef = useRef("trigger");
    this.menuRef = useRef("menu");
    this._menuLayoutListenersAttached = false;
    this._onMenuLayoutEvent = this._onMenuLayoutEvent.bind(this);
    this.state = useState({
      data: null,
      menuOpen: false,
      saving: false,
      current: "normal",
      loaded: false,
      selectorEnabled: true,
    });
    this._interval = null;
    this._onComposerInput = this._onComposerInput.bind(this);
    this._onDocClick = this._onDocClick.bind(this);
    window.addEventListener("llm-experience-refresh-meter", this._onComposerInput);
    onMounted(() => {
      document.addEventListener("click", this._onDocClick);
    });
    onWillUnmount(() => {
      this._detachMenuLayoutListeners();
      window.removeEventListener("llm-experience-refresh-meter", this._onComposerInput);
      document.removeEventListener("click", this._onDocClick);
      if (this._interval) {
        clearInterval(this._interval);
      }
    });
    onWillUpdateProps((next) => {
      if (next.threadId !== this.props.threadId) {
        this.state.menuOpen = false;
        this.fetch();
      }
    });
    onWillStart(() => this.fetch());
    this._interval = setInterval(() => this.fetch(), 12000);
    onPatched(() => {
      if (this.state.menuOpen) {
        requestAnimationFrame(() => {
          this._syncMenuFixedPosition();
          requestAnimationFrame(() => this._syncMenuFixedPosition());
        });
        this._attachMenuLayoutListeners();
      } else {
        this._detachMenuLayoutListeners();
        this._clearMenuFixedStyles();
      }
    });
  }

  _attachMenuLayoutListeners() {
    if (this._menuLayoutListenersAttached) {
      return;
    }
    this._menuLayoutListenersAttached = true;
    window.addEventListener("resize", this._onMenuLayoutEvent);
    window.addEventListener("scroll", this._onMenuLayoutEvent, true);
  }

  _detachMenuLayoutListeners() {
    if (!this._menuLayoutListenersAttached) {
      return;
    }
    this._menuLayoutListenersAttached = false;
    window.removeEventListener("resize", this._onMenuLayoutEvent);
    window.removeEventListener("scroll", this._onMenuLayoutEvent, true);
  }

  _onMenuLayoutEvent() {
    if (this.state.menuOpen) {
      this._syncMenuFixedPosition();
    }
  }

  /**
   * Menú en coordenadas de viewport: evita recortes por overflow en ancestros
   * (p. ej. .o_LLMChat_content). Alinea el borde izquierdo al del gauge y
   * ajusta dentro de la ventana.
   */
  _syncMenuFixedPosition() {
    const menu = this.menuRef.el;
    const trigger = this.triggerRef.el;
    if (!menu || !trigger) {
      return;
    }
    const rect = trigger.getBoundingClientRect();
    const pad = 8;
    const gap = 6;
    const mw = menu.offsetWidth || 220;
    const mh = menu.offsetHeight || 1;
    let left = rect.left;
    if (left + mw > window.innerWidth - pad) {
      left = window.innerWidth - pad - mw;
    }
    if (left < pad) {
      left = pad;
    }
    let top = rect.top - mh - gap;
    if (top < pad) {
      top = rect.bottom + gap;
    }
    if (top + mh > window.innerHeight - pad) {
      top = Math.max(pad, window.innerHeight - pad - mh);
    }
    menu.style.position = "fixed";
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.style.right = "auto";
    menu.style.bottom = "auto";
    menu.style.transform = "none";
    menu.style.zIndex = "1080";
  }

  _clearMenuFixedStyles() {
    const menu = this.menuRef.el;
    if (!menu) {
      return;
    }
    menu.style.position = "";
    menu.style.left = "";
    menu.style.top = "";
    menu.style.right = "";
    menu.style.bottom = "";
    menu.style.transform = "";
    menu.style.zIndex = "";
  }

  _onComposerInput() {
    this.fetch();
  }

  _onDocClick(ev) {
    if (!this.state.menuOpen) {
      return;
    }
    const el = this.rootRef.el;
    if (el && !el.contains(ev.target)) {
      this.state.menuOpen = false;
      this._detachMenuLayoutListeners();
    }
  }

  async fetch() {
    const tid = this.props.threadId;
    if (!tid) {
      this.state.data = null;
      return;
    }
    try {
      const data = await this.orm.call("llm.thread", "experience_meter_rpc", [tid]);
      if (data && !data.error) {
        this.state.data = data;
        this.state.current = data.work_mode || "normal";
        this.state.selectorEnabled = data.work_mode_selector_enabled !== false;
        this.state.loaded = true;
      } else {
        this.state.data = null;
        this.state.loaded = true;
      }
    } catch (e) {
      this.state.data = null;
      this.state.loaded = true;
    }
  }

  get options() {
    return MODES;
  }

  get currentOption() {
    return MODES.find((m) => m.value === this.state.current) || MODES[0];
  }

  get ariaLabel() {
    return `Contexto y modo: ${this.currentOption.label}`;
  }

  get ariaExpanded() {
    return this.state.menuOpen ? "true" : "false";
  }

  get pct() {
    const d = this.state.data;
    if (!d || !d.limit) {
      return 0;
    }
    return Math.min(100, Math.round((100 * (d.live || 0)) / d.limit));
  }

  get ringFillClass() {
    const s = this.state.data?.state;
    let suf = "normal";
    if (s === "critical") {
      suf = "critical";
    } else if (s === "warning") {
      suf = "warning";
    }
    return `o_llm_ctxMeter__ring-fill o_llm_ctxMeter__ring-fill--${suf}`;
  }

  get gaugeCircumference() {
    return 2 * Math.PI * GAUGE_R;
  }

  get gaugeDashArray() {
    return String(this.gaugeCircumference);
  }

  get gaugeDashOffset() {
    const c = this.gaugeCircumference;
    return c * (1 - this.pct / 100);
  }

  get ctxTitle() {
    const d = this.state.data;
    if (!d) {
      return "";
    }
    const last = d.last || {};
    const costUsd =
      d.cost_usd_total !== undefined && d.cost_usd_total !== null
        ? Number(d.cost_usd_total)
        : null;
    const costCur = d.cost_currency || "USD";
    const lines = [
      `Contexto: ${d.live || 0} / ${d.limit || 0} tokens (${this.pct}%).`,
      `Modo: ${this.currentOption.label} (${this.currentOption.abbr}).`,
      `Umbrales: aviso ~${Math.round((d.soft_ratio || 0.8) * 100)} % · compactación ~${Math.round((d.hard_ratio || 0.92) * 100)} %.`,
    ];
    if (costUsd !== null && !Number.isNaN(costUsd)) {
      lines.splice(
        1,
        0,
        `Coste USD acumulado: ${costUsd.toFixed(6)} ${costCur}.`
      );
    }
    if (last.prompt != null || last.output != null) {
      lines.push(
        `Última respuesta: prompt ${last.prompt || 0}, salida ${last.output || 0}, caché ${last.cached || 0}, pensamiento ${last.thoughts || 0}.`
      );
    }
    if (d.billable_accumulated) {
      lines.push(`Acumulado facturable (tokens): ${d.billable_accumulated}.`);
    }
    if (d.compaction_count) {
      lines.push(`Compactaciones: ${d.compaction_count}.`);
    }
    if (this.state.selectorEnabled) {
      lines.push("Clic en el gauge para cambiar el modo de trabajo.");
    }
    return lines.join("\n");
  }

  toggleMenu(ev) {
    ev.stopPropagation();
    if (this.state.saving || !this.state.selectorEnabled) {
      return;
    }
    this.state.menuOpen = !this.state.menuOpen;
  }

  onPickMode(ev) {
    ev.stopPropagation();
    const mode = ev.currentTarget.getAttribute("data-mode");
    if (mode) {
      this.selectMode(mode, ev);
    }
  }

  async selectMode(mode, ev) {
    if (ev) {
      ev.stopPropagation();
    }
    const tid = this.props.threadId;
    if (!tid || this.state.saving || mode === this.state.current) {
      this.state.menuOpen = false;
      return;
    }
    this.state.saving = true;
    this.state.menuOpen = false;
    try {
      await this.orm.write("llm.thread", [tid], { chat_work_mode: mode });
      this.state.current = mode;
      window.dispatchEvent(new CustomEvent("llm-experience-refresh-meter"));
    } catch (e) {
      console.warn("llm_experience: no se pudo guardar modo de trabajo", e);
    } finally {
      this.state.saving = false;
    }
  }
}

LLMContextMeter.template = "llm_experience.LLMContextMeter";
LLMContextMeter.props = {
  threadId: { type: Number, optional: true },
};

registerMessagingComponent(LLMContextMeter);
