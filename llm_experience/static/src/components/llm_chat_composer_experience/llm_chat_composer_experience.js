/** @odoo-module **/

import "../llm_context_meter/llm_context_meter";
import { registerPatch } from "@mail/model/model_core";

function _refreshMeter() {
  window.dispatchEvent(new CustomEvent("llm-experience-refresh-meter"));
}

registerPatch({
  name: "Composer",
  recordMethods: {
    async postUserMessageForLLM() {
      await this._super(...arguments);
      if (this.thread?.model === "llm.thread") {
        _refreshMeter();
      }
    },
    _dispatchStreamEvent(data) {
      this._super(...arguments);
      if (
        this.thread?.model === "llm.thread" &&
        (data.type === "done" || data.type === "error")
      ) {
        _refreshMeter();
      }
    },
  },
});
