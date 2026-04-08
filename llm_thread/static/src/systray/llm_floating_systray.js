/** @odoo-module **/

import { Dropdown, DROPDOWN } from "@web/core/dropdown/dropdown";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { useModels } from "@mail/component_hooks/use_models";
import { getMessagingComponent } from "@mail/utils/messaging_component";

import { Component, onWillStart, useState } from "@odoo/owl";

/** Debe coincidir con el action.id usado en initializeLLMChat para el ámbito del chat. */
export const LLM_SYSTRAY_ACTION_ID = "llm_systray_float";

/** Escala base html2canvas; con scroll corto se mantiene ligera. */
const LLM_CAPTURE_HTML2CANVAS_SCALE = 0.65;
/** Límite conservador por lado del canvas (Chrome suele permitir ~16384). */
const LLM_CAPTURE_MAX_CANVAS_SIDE = 12288;

/**
 * Cuerpo del menú bajo el icono de barita: debe ser hijo directo de `Dropdown`
 * para tener `env[DROPDOWN]` y poder cerrar el menú al elegir un hilo.
 */
export class LLMFloatingSystrayMenuBody extends Component {
  async onClickThreadRow(ev) {
    const id = Number(ev.currentTarget.dataset.threadId);
    if (!id) {
      return;
    }
    await this.props.systray.openThread(id);
    this.env[DROPDOWN]?.close?.();
  }

  async onClickNewChat() {
    await this.props.systray.onClickNewChat();
    this.env[DROPDOWN]?.close?.();
  }

  onClickLoadMore() {
    this.props.systray.loadMoreBrowse();
  }
}

LLMFloatingSystrayMenuBody.template = "llm_thread.LLMFloatingSystrayMenuBody";
LLMFloatingSystrayMenuBody.props = {
  systray: { type: Object },
};

export class LLMFloatingSystray extends Component {
  setup() {
    useModels();
    this.user = useService("user");
    this.action = useService("action");
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.ui = useService("ui");

    this.state = useState({
      showSystray: false,
      search: "",
      browseThreads: [],
      browseOffset: 0,
      hasMoreBrowse: false,
      searchMode: false,
      searchResults: [],
      panelOpen: false,
      panelMinimized: false,
      loadingThreads: false,
      loadingMore: false,
      searchingRemote: false,
      initializing: false,
    });

    this._debouncedSearch = debounce(() => this._runSearchRemote(), 400);

    onWillStart(async () => {
      this.state.showSystray = await this.user.hasGroup(
        "llm_thread.group_llm_floating_chat"
      );
    });

    this.onDropdownBeforeOpen = async () => {
      this.state.search = "";
      this.state.searchMode = false;
      this.state.searchResults = [];
      await this.loadBrowseFirstPage();
    };
  }

  get menuBodyProps() {
    return { systray: this };
  }

  /**
   * Props del Dropdown (posición y ancho del menú según tamaño de pantalla).
   */
  get dropdownSystrayProps() {
    return {
      class: "o_menu_systray_item o_llm_floating_systray_dropdown",
      position: this.ui.isSmall ? "bottom" : "bottom-end",
      togglerClass: "o-dropdown-toggle o-dropdown--narrow border-0",
      beforeOpen: this.onDropdownBeforeOpen,
      menuClass: this.ui.isSmall
        ? "o_llm_floating_systray_menu p-0 o_llm_floating_systray_menu--mobile o_llm_floating_systray_menu--fullscreen"
        : "o_llm_floating_systray_menu p-0",
    };
  }

  get displayedThreads() {
    if (this.state.searchMode && (this.state.search || "").trim()) {
      return this.state.searchResults;
    }
    return this.state.browseThreads;
  }

  get messaging() {
    return this.env.services.messaging.modelManager.messaging;
  }

  /**
   * Si el chat IA a pantalla completa está activo, no mostramos el panel flotante
   * para evitar dos instancias del mismo componente.
   */
  get isFullLlmChatAction() {
    const ctrl = this.action.currentController;
    return ctrl?.action?.tag === "llm_thread.chat_client_action";
  }

  get canShowFloatingPanel() {
    return this.state.panelOpen && !this.isFullLlmChatAction;
  }

  /**
   * Título del hilo en la barra morada. Lee `activeThread.name` para que useModels
   * vuelva a renderizar cuando el nombre se actualice en el modelo mail.
   */
  get floatingPanelTitle() {
    const t = this.messaging.llmChat?.activeThread;
    const raw = t?.name;
    if (raw !== undefined && raw !== null && String(raw).trim() !== "") {
      return String(raw).trim();
    }
    return this.env._t("Chat IA");
  }

  async loadBrowseFirstPage() {
    this.state.loadingThreads = true;
    try {
      const uid = this.user.userId;
      const threads = await this.orm.searchRead(
        "llm.thread",
        [["user_id", "=", uid]],
        ["name", "write_date"],
        { order: "write_date desc", limit: 30, offset: 0 }
      );
      this.state.browseThreads = threads;
      this.state.browseOffset = threads.length;
      this.state.hasMoreBrowse = threads.length === 30;
    } catch (e) {
      console.error("LLMFloatingSystray.loadBrowseFirstPage", e);
      this.notification.add(
        this.env._t("No se pudieron cargar las conversaciones."),
        { type: "danger" }
      );
    } finally {
      this.state.loadingThreads = false;
    }
  }

  async loadMoreBrowse() {
    if (!this.state.hasMoreBrowse || this.state.loadingMore || this.state.searchMode) {
      return;
    }
    this.state.loadingMore = true;
    try {
      const uid = this.user.userId;
      const threads = await this.orm.searchRead(
        "llm.thread",
        [["user_id", "=", uid]],
        ["name", "write_date"],
        { order: "write_date desc", limit: 30, offset: this.state.browseOffset }
      );
      this.state.browseThreads = [...this.state.browseThreads, ...threads];
      this.state.browseOffset += threads.length;
      this.state.hasMoreBrowse = threads.length === 30;
    } catch (e) {
      console.error("LLMFloatingSystray.loadMoreBrowse", e);
      this.notification.add(
        this.env._t("No se pudieron cargar más conversaciones."),
        { type: "danger" }
      );
    } finally {
      this.state.loadingMore = false;
    }
  }

  onSearchInput(ev) {
    const v = ev.target.value || "";
    this.state.search = v;
    const q = v.trim();
    if (!q) {
      this.state.searchMode = false;
      this.state.searchResults = [];
      this.state.searchingRemote = false;
      this._debouncedSearch.cancel();
      return;
    }
    this.state.searchMode = true;
    this.state.searchingRemote = true;
    this._debouncedSearch();
  }

  async _runSearchRemote() {
    const q = (this.state.search || "").trim();
    if (!q) {
      this.state.searchMode = false;
      this.state.searchResults = [];
      return;
    }
    this.state.searchingRemote = true;
    try {
      const uid = this.user.userId;
      const threads = await this.orm.searchRead(
        "llm.thread",
        [
          ["user_id", "=", uid],
          ["name", "ilike", `%${q}%`],
        ],
        ["name", "write_date"],
        { order: "write_date desc", limit: 500 }
      );
      this.state.searchResults = threads;
    } catch (e) {
      console.error("LLMFloatingSystray._runSearchRemote", e);
      this.notification.add(this.env._t("Error al buscar conversaciones."), {
        type: "danger",
      });
    } finally {
      this.state.searchingRemote = false;
    }
  }

  async onClickNewChat() {
    this.state.initializing = true;
    try {
      const llmChat = this.messaging.llmChat;
      llmChat.update({ isSystrayFloatingMode: true });
      await this.messaging.initializedPromise;
      await llmChat.ensureDataLoaded();
      const thread = await llmChat.createThread({});
      if (thread) {
        await this.loadBrowseFirstPage();
        await this.openThread(thread.id);
      }
    } catch (e) {
      console.error("LLMFloatingSystray.onClickNewChat", e);
    } finally {
      this.state.initializing = false;
    }
  }

  /**
   * Abre el panel flotante y carga el hilo indicado.
   */
  async openThread(threadId) {
    this.state.panelOpen = true;
    this.state.panelMinimized = false;
    const llmChat = this.messaging.llmChat;
    llmChat.update({ isSystrayFloatingMode: true });
    await this.messaging.initializedPromise;

    const systrayScopeKey = `${LLM_SYSTRAY_ACTION_ID}|`;
    const alreadySystray =
      llmChat.chatInitScopeKey === systrayScopeKey && llmChat.llmChatView;

    if (!alreadySystray) {
      this.state.initializing = true;
      try {
        const action = {
          id: LLM_SYSTRAY_ACTION_ID,
          name: this.env._t("Chat IA flotante"),
          context: {},
        };
        await llmChat.initializeLLMChat(
          action,
          `llm.thread_${threadId}`,
          []
        );
      } catch (e) {
        console.error("LLMFloatingSystray.openThread", e);
        this.notification.add(
          this.env._t("No se pudo abrir la conversación."),
          { type: "danger" }
        );
        this.state.initializing = false;
        return;
      } finally {
        this.state.initializing = false;
      }
    }

    try {
      await llmChat.selectThread(threadId);
    } catch (e) {
      console.error("LLMFloatingSystray.selectThread", e);
      this.notification.add(
        this.env._t("No se pudo abrir la conversación."),
        { type: "danger" }
      );
    }
  }

  onClickFullChat() {
    const active = this.messaging.llmChat?.activeThread;
    if (!active) {
      return;
    }
    this.state.panelOpen = false;
    this.state.panelMinimized = false;
    this.messaging.llmChat.update({ isSystrayFloatingMode: false });
    this.action.doAction("llm_thread.action_llm_chat", {
      active_id: this.messaging.llmChat.threadToActiveId(active),
      clearBreadcrumbs: false,
    });
  }

  onClosePanel() {
    this.state.panelOpen = false;
    this.state.panelMinimized = false;
    this.messaging.llmChat?.update({ isSystrayFloatingMode: false });
  }

  onClickMinimizePanel() {
    this.state.panelMinimized = true;
  }

  onClickRestorePanel() {
    this.state.panelMinimized = false;
  }

  onClickFloatingHeaderBar() {
    if (this.state.panelMinimized) {
      this.onClickRestorePanel();
    }
  }

  noop() {}

  /**
   * Ancho y alto lógicos para capturar la vista completa, incluyendo regiones con scroll interno.
   */
  _getCaptureFullDimensions(target) {
    const docEl = document.documentElement;
    const body = document.body;
    let maxW = Math.max(
      target.scrollWidth,
      target.clientWidth,
      target.offsetWidth
    );
    let maxH = Math.max(
      target.scrollHeight,
      target.clientHeight,
      target.offsetHeight
    );
    target.querySelectorAll("*").forEach((node) => {
      try {
        if (node.scrollHeight > node.clientHeight + 2) {
          maxH = Math.max(maxH, node.scrollHeight);
        }
        if (node.scrollWidth > node.clientWidth + 2) {
          maxW = Math.max(maxW, node.scrollWidth);
        }
      } catch (e) {
        /* nodos sin layout */
      }
    });
    try {
      const reportBody = target.querySelector(".o_account_reports_body");
      if (reportBody) {
        maxH = Math.max(
          maxH,
          reportBody.scrollHeight,
          reportBody.offsetHeight
        );
        maxW = Math.max(
          maxW,
          reportBody.scrollWidth,
          reportBody.offsetWidth
        );
      }
    } catch (e) {
      /* ignore */
    }
    if (target === body || target === docEl) {
      maxW = Math.ceil(
        Math.max(maxW, docEl.scrollWidth, body ? body.scrollWidth : 0)
      );
      maxH = Math.ceil(
        Math.max(maxH, docEl.scrollHeight, body ? body.scrollHeight : 0)
      );
    } else {
      maxW = Math.ceil(maxW);
      maxH = Math.ceil(maxH);
    }
    return {
      width: Math.max(1, maxW),
      height: Math.max(1, maxH),
    };
  }

  /**
   * Escala html2canvas: sube la resolución cuando el contenido es muy alto (informes
   * contables, listas largas) para que el texto no quede borroso; acotada al máximo
   * del canvas del navegador.
   */
  _computeAdaptiveHtml2CanvasScale(fullWidth, fullHeight) {
    const base = LLM_CAPTURE_HTML2CANVAS_SCALE;
    const h = fullHeight;
    const w = fullWidth;
    // Cuanto más largo el scroll vertical, más escala (hasta ~1.0+)
    const heightBoost = Math.min(0.34, Math.max(0, (h - 2000) / 10500));
    let scale = base + heightBoost;
    // Scroll horizontal muy ancho: pequeño extra
    if (w > 2400) {
      scale += Math.min(0.06, (w - 2400) / 20000);
    }
    scale = Math.min(scale, 1.05);
    // Pantallas HiDPI: ligero extra solo si DPR > 1 (no penalizar monitores 1x)
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (h > 2800 && dpr > 1) {
      const dprBoost = Math.min(1.12, 1 + 0.08 * (dpr - 1));
      scale *= dprBoost;
    }
    // No superar el lado máximo del canvas (evita fallos o degradación del navegador)
    const capW = LLM_CAPTURE_MAX_CANVAS_SIDE / w;
    const capH = LLM_CAPTURE_MAX_CANVAS_SIDE / h;
    scale = Math.min(scale, capW, capH);
    return Math.max(0.52, scale);
  }

  /**
   * Opciones html2canvas: pantalla completa de la zona de acción (scroll + scroll interno)
   * y calidad algo mayor que la captura solo de viewport.
   */
  _getHtml2CanvasFullPageOptions(target) {
    const { width: fullWidth, height: fullHeight } =
      this._getCaptureFullDimensions(target);
    const scale = this._computeAdaptiveHtml2CanvasScale(fullWidth, fullHeight);
    return {
      scale,
      useCORS: true,
      logging: false,
      allowTaint: false,
      imageTimeout: 20000,
      width: fullWidth,
      height: fullHeight,
      windowWidth: fullWidth,
      windowHeight: fullHeight,
      scrollX: 0,
      scrollY: 0,
      onclone: (clonedDoc, referenceElement) => {
        const scope =
          referenceElement ||
          clonedDoc.querySelector(".o_action_manager") ||
          clonedDoc.body;
        const selectors = [
          ".o_action_manager",
          ".o_content",
          ".o_view_controller",
          ".o_list_view",
          ".o_list_renderer",
          ".o_form_view",
          ".o_kanban_view",
          ".o_graph_view",
          ".o_pivot_view",
          ".o_account_reports_body",
          ".o_account_reports_page",
        ];
        selectors.forEach((sel) => {
          clonedDoc.querySelectorAll(sel).forEach((node) => {
            if (node.style) {
              node.style.overflow = "visible";
              node.style.maxHeight = "none";
            }
          });
        });
        if (scope && scope.style) {
          scope.style.overflow = "visible";
          scope.style.maxHeight = "none";
        }
      },
    };
  }

  async onClickCaptureVisual() {
    const h2c = window.html2canvas;
    const target = document.querySelector(".o_action_manager") || document.body;
    if (typeof h2c !== "function") {
      await this.onClickContextText();
      this.notification.add(
        this.env._t(
          "La captura visual no está disponible; se insertó solo el contexto en texto."
        ),
        { type: "warning" }
      );
      return;
    }
    try {
      const opts = this._getHtml2CanvasFullPageOptions(target);
      const canvas = await h2c(target, opts);
      const blob = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/png")
      );
      if (!blob) {
        await this.onClickContextText();
        return;
      }
      const file = new File(
        [blob],
        `captura-pantalla-${Date.now()}.png`,
        { type: "image/png" }
      );
      const cv =
        this.messaging.llmChat?.llmChatView?.composer?.composerViews?.[0];
      if (cv?.fileUploader) {
        cv.fileUploader.uploadFiles([file]);
      } else {
        await this.onClickContextText();
      }
    } catch (e) {
      console.error("LLMFloatingSystray.onClickCaptureVisual", e);
      await this.onClickContextText();
      this.notification.add(
        this.env._t(
          "No se pudo generar la imagen; se insertó el contexto en texto."
        ),
        { type: "warning" }
      );
    }
  }

  async onClickContextText() {
    const lines = this._gatherContextLines();
    const block = lines.join("\n");
    const composer = this.messaging.llmChat?.llmChatView?.composer;
    const cv = composer?.composerViews?.[0];
    if (cv?.composer) {
      const prev = cv.composer.textInputContent || "";
      cv.composer.update({
        textInputContent: `[${this.env._t("Contexto de pantalla")}]\n${block}\n\n${prev}`,
      });
      cv.update({ doFocus: true });
    }
  }

  _gatherContextLines() {
    const lines = [];
    lines.push(`${this.env._t("URL")}: ${window.location.href}`);
    lines.push(`${this.env._t("Título")}: ${document.title}`);
    const ctrl = this.action.currentController;
    const act = ctrl?.action;
    if (act?.name) {
      lines.push(`${this.env._t("Acción")}: ${act.name}`);
    }
    if (ctrl?.props?.resModel) {
      lines.push(`${this.env._t("Modelo")}: ${ctrl.props.resModel}`);
    }
    if (ctrl?.props?.resId) {
      lines.push(`${this.env._t("Registro ID")}: ${ctrl.props.resId}`);
    }
    return lines;
  }
}

Object.assign(LLMFloatingSystray, {
  components: {
    Dropdown,
    LLMChat: getMessagingComponent("LLMChat"),
    LLMFloatingSystrayMenuBody,
  },
  template: "llm_thread.LLMFloatingSystray",
});

registry.category("systray").add(
  "llm_thread.LLMFloatingSystray",
  { Component: LLMFloatingSystray },
  { sequence: 26 }
);
