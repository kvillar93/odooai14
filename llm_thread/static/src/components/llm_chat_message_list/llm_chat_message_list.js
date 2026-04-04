/** @odoo-module **/

import { onMounted, onPatched, useEffect, useRef } from "@odoo/owl";
import { MessageList } from "@mail/components/message_list/message_list";
import { Transition } from "@web/core/transition";
import { registerMessagingComponent } from "@mail/utils/messaging_component";

export class LLMChatMessageList extends MessageList {
  setup() {
    super.setup();
    this.rootRef = useRef("root");
    this._llmScrollRaf = null;

    onMounted(() => {
      this._scrollToEnd();
    });

    useEffect(
      () => {
        this._scrollToEnd();
      },
      () => [this.thread?.id, this.isStreaming]
    );

    // Chunks de streaming: el cuerpo del mensaje cambia sin variar thread ni el flag isStreaming (sigue true).
    onPatched(() => {
      if (this.composerView?.composer?.isStreaming) {
        this._scheduleScrollToEnd();
      }
    });
  }

  get thread() {
    return this.composerView?.composer?.thread;
  }

  get composerView() {
    return this.props.composerView;
  }

  get isStreaming() {
    return Boolean(this.composerView?.composer?.isStreaming);
  }

  _scheduleScrollToEnd() {
    if (this._llmScrollRaf) {
      return;
    }
    this._llmScrollRaf = requestAnimationFrame(() => {
      this._llmScrollRaf = null;
      this._scrollToEnd();
    });
  }

  _scrollToEnd() {
    const root = this.rootRef.el;
    if (!root) {
      return;
    }
    const outer = root.closest(".o_LLMChatThread_content");
    const setEnd = (el) => {
      if (!el) {
        return;
      }
      el.scrollTop = el.scrollHeight - el.clientHeight;
    };
    // Puede haber scroll en el panel del hilo y/o en la lista de mensajes (overflow anidado).
    setEnd(outer);
    setEnd(root);
  }
}

Object.assign(LLMChatMessageList, {
  components: { Transition },
  props: { record: Object, composerView: Object },
  template: "llm_thread.LLMChatMessageList",
});

registerMessagingComponent(LLMChatMessageList);
