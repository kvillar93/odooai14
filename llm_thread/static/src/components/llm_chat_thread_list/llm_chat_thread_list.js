/** @odoo-module **/

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { registerMessagingComponent } from "@mail/utils/messaging_component";
import { useModels } from "@mail/component_hooks/use_models";

import { Component, useState } from "@odoo/owl";

export class LLMChatThreadList extends Component {
  setup() {
    useModels();
    super.setup();
    this.dialog = useService("dialog");
    this.orm = useService("orm");
    this.state = useState({
      isLoading: false,
      searchQuery: "",
    });
  }

  onSearchInput(ev) {
    this.state.searchQuery = ev.target.value || "";
  }

  /**
   * Hilos filtrados por nombre (sin scroll horizontal: títulos truncados en plantilla).
   */
  get filteredThreads() {
    const threads = this.llmChatView.llmChat.orderedThreads || [];
    const q = (this.state.searchQuery || "").trim().toLowerCase();
    if (!q) {
      return threads;
    }
    return threads.filter((t) =>
      (t.name || "").toLowerCase().includes(q)
    );
  }

  /**
   * @returns {LLMChatView}
   */
  get llmChatView() {
    return this.props.record;
  }

  get messaging() {
    return this.llmChatView.messaging;
  }

  /**
   * @returns {Thread}
   */
  get activeThread() {
    return this.llmChatView.llmChat.activeThread;
  }

  /**
   * Handle thread click
   * @param {Thread} thread
   */
  async _onThreadClick(thread) {
    if (this.state.isLoading) return;

    this.state.isLoading = true;
    try {
      await this.llmChatView.llmChat.selectThread(thread.id);
      this.llmChatView.update({
        isThreadListVisible: false,
      });
    } catch (error) {
      console.error("Error selecting thread:", error);
      this.messaging.notify({
        title: "Error",
        message: "Failed to load thread",
        type: "danger",
      });
    } finally {
      this.state.isLoading = false;
    }
  }

  /**
   * @param {Event} ev
   * @param {Thread} thread
   */
  _onDeleteClick(ev, thread) {
    ev.preventDefault();
    ev.stopPropagation();
    this.dialog.add(ConfirmationDialog, {
      title: this.env._t("Eliminar conversación"),
      body: this.env._t(
        "¿Eliminar esta conversación de forma permanente? Esta acción no se puede deshacer."
      ),
      confirmLabel: this.env._t("Eliminar"),
      cancelLabel: this.env._t("Cancelar"),
      confirm: async () => {
        const llmChat = this.llmChatView.llmChat;
        const deletedId = thread.id;
        const wasActive = llmChat.activeThread?.id === deletedId;
        await this.orm.unlink("llm.thread", [deletedId]);
        await llmChat.loadThreads();
        if (wasActive) {
          const remaining = llmChat.orderedThreads;
          if (remaining.length > 0) {
            await llmChat.selectThread(remaining[0].id);
          } else {
            await llmChat.createNewThread();
          }
        }
      },
    });
  }
}

Object.assign(LLMChatThreadList, {
  props: { record: Object },
  template: "llm_thread.LLMChatThreadList",
});

registerMessagingComponent(LLMChatThreadList);
