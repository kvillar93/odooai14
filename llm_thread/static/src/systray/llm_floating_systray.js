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

/** Tamaño máximo del HTML adjunto (caracteres) para no colgar el navegador. */
const LLM_ACTIVE_VIEW_HTML_MAX_CHARS = 2_500_000;

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

  _escapeHtmlForSnapshot(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * Nombre de archivo seguro a partir de `document.title` (p. ej. pestaña «Odoo - Pérdidas y ganancias»).
   */
  _sanitizeFilenameFromPageTitle() {
    let s = (document.title || "").trim();
    s = s.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "");
    s = s.replace(/\s+/g, "-");
    s = s.replace(/-+/g, "-").replace(/^-|-$/g, "");
    if (s.length > 100) {
      s = s.slice(0, 100).replace(/-+$/g, "");
    }
    if (!s) {
      return `documento-${Date.now()}`;
    }
    return s;
  }

  /**
   * Serializa el HTML de la zona de acción actual (`.o_action_manager`) para el LLM.
   * Clona el DOM, elimina scripts/iframes y envuelve en un documento mínimo con metadatos.
   */
  _buildActiveViewHtmlDocument() {
    const root =
      document.querySelector(".o_action_manager") || document.body;
    const clone = root.cloneNode(true);
    clone.querySelectorAll("script, iframe, object, embed").forEach((n) => {
      n.remove();
    });
    const ctrl = this.action.currentController;
    const act = ctrl?.action;
    const metaLines = [
      `${this.env._t("URL")}: ${window.location.href}`,
      `${this.env._t("Título")}: ${document.title}`,
    ];
    if (act?.name) {
      metaLines.push(`${this.env._t("Acción")}: ${act.name}`);
    }
    if (ctrl?.props?.resModel) {
      metaLines.push(`${this.env._t("Modelo")}: ${ctrl.props.resModel}`);
    }
    if (ctrl?.props?.resId) {
      metaLines.push(`${this.env._t("Registro ID")}: ${ctrl.props.resId}`);
    }
    const metaComment = `<!--\n${metaLines.join("\n")}\n-->`;
    const title = this._escapeHtmlForSnapshot(document.title);
    return `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width"/>
<title>${title}</title>
</head>
<body>
${metaComment}
${clone.outerHTML}
</body>
</html>`;
  }

  /**
   * Adjunta un archivo .html con el DOM de la vista activa (ligero para el navegador).
   */
  async onClickAttachActiveViewHtml() {
    const cv =
      this.messaging.llmChat?.llmChatView?.composer?.composerViews?.[0];
    if (!cv?.fileUploader) {
      this.notification.add(
        this.env._t("Abre un chat y el compositor para adjuntar la vista."),
        { type: "warning" }
      );
      return;
    }
    try {
      let html = this._buildActiveViewHtmlDocument();
      let truncated = false;
      if (html.length > LLM_ACTIVE_VIEW_HTML_MAX_CHARS) {
        html =
          html.slice(0, LLM_ACTIVE_VIEW_HTML_MAX_CHARS) +
          `\n\n<!-- ${this.env._t(
            "Contenido truncado por tamaño máximo."
          )} -->\n`;
        truncated = true;
      }
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const fileName = `${this._sanitizeFilenameFromPageTitle()}.html`;
      const file = new File([blob], fileName, { type: "text/html" });
      cv.fileUploader.uploadFiles([file]);
      if (truncated) {
        this.notification.add(
          this.env._t(
            "El HTML se ha truncado por tamaño; adjunta solo una parte de la vista."
          ),
          { type: "warning" }
        );
      }
    } catch (e) {
      console.error("LLMFloatingSystray.onClickAttachActiveViewHtml", e);
      this.notification.add(
        this.env._t("No se pudo generar el HTML de la vista."),
        { type: "danger" }
      );
    }
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
