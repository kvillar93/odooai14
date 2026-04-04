/** @odoo-module **/

import { registerMessagingComponent } from "@mail/utils/messaging_component";

const { Component } = owl;

const ANALYZING_LABEL = "Analizando";

export class LLMChatThread extends Component {
  setup() {
    this.starterPrompts = [
      {
        icon: "fa-lightbulb-o",
        label: "Ventajas de CRM y ventas en Odoo",
        text: "Resume en viñetas las ventajas de usar CRM y ventas integrados en Odoo para una pyme.",
      },
      {
        icon: "fa-table",
        label: "Tabla de ejemplo en Markdown",
        text: "Genera una tabla Markdown de ejemplo con columnas Cliente, Pedido, Total y Estado.",
      },
      {
        icon: "fa-line-chart",
        label: "Interpretar un informe de facturación",
        text: "Explícame paso a paso cómo interpretar un informe de facturación mensual en Odoo.",
      },
      {
        icon: "fa-code",
        label: "Consulta SQL de solo lectura",
        text: "Escribe un SELECT de solo lectura que liste las últimas 10 facturas publicadas con importe y partner.",
      },
    ];
  }

  get threadView() {
    return this.props.threadView;
  }

  /**
   * @returns {Thread}
   */
  get thread() {
    return this.props.record;
  }

  get analyzingChars() {
    return [...ANALYZING_LABEL];
  }

  /**
   * @returns {Message[]}
   */
  get messages() {
    return this.thread.cache?.orderedMessages || [];
  }

  get showConversationStarters() {
    const cache = this.thread?.cache;
    if (!cache || cache.isLoading) {
      return false;
    }
    const nonEmpty = cache.orderedNonEmptyMessages;
    return nonEmpty && nonEmpty.length === 0;
  }

  /**
   * @param {string} text
   */
  onClickStarter(text) {
    const cv = this.threadView?.composerView;
    if (!cv?.composer) {
      return;
    }
    cv.composer.update({ textInputContent: text });
    const ta =
      cv.textareaRef?.el ||
      cv.mirroredTextareaRef?.el ||
      document.querySelector(".o_LLMChatComposer textarea");
    if (ta && typeof ta.focus === "function") {
      ta.focus();
      if (typeof ta.setSelectionRange === "function") {
        const n = text.length;
        ta.setSelectionRange(n, n);
      }
    }
  }
}

Object.assign(LLMChatThread, {
  props: {
    record: Object,
    threadView: Object,
  },
  template: "llm_thread.LLMChatThread",
});

registerMessagingComponent(LLMChatThread);
