/** @odoo-module **/

import { attr } from "@mail/model/model_field";
import { registerPatch } from "@mail/model/model_core";

registerPatch({
  name: "Message",
  fields: {
    /**
     * Check if this is a user generation message
     */
    isLLMUserGenerationMessage: attr({
      compute() {
        return this.llmRole === "user" && Boolean(this.bodyJson);
      },
    }),

    /**
     * Get formatted generation data for display
     */
    generationDataFormatted: attr({
      compute() {
        if (!this.bodyJson || Object.keys(this.bodyJson).length === 0) {
          return "{}";
        }

        try {
          return JSON.stringify(this.bodyJson, null, 2);
        } catch (e) {
          return String(this.bodyJson);
        }
      },
    }),
  },
});
