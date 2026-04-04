/** @odoo-module **/

import { attr } from "@mail/model/model_field";
import { registerPatch } from "@mail/model/model_core";

registerPatch({
  name: "LLMModel",
  fields: {
    /**
     * Model usage type (chat, embedding, image_generation, etc.)
     */
    modelUse: attr(),

    /**
     * Model details JSON field
     */
    details: attr(),

    /**
     * Check if this model is configured for media generation
     * Based purely on model_use field containing "generation"
     */
    isMediaGenerationModel: attr({
      compute() {
        if (!this.modelUse) {
          return false;
        }

        // Check if model_use contains "generation"
        const generationTypes = ["image_generation", "generation"];
        return generationTypes.includes(this.modelUse);
      },
    }),

    /**
     * Get the input schema from details field
     */
    inputSchema: attr({
      compute() {
        return this.details?.input_schema || {};
      },
    }),

    /**
     * Get the output schema from details field
     */
    outputSchema: attr({
      compute() {
        return this.details?.output_schema || {};
      },
    }),
  },
});
