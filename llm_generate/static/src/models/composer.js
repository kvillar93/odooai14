/** @odoo-module **/

import { registerPatch } from "@mail/model/model_core";

registerPatch({
  name: "Composer",
  recordMethods: {
    /**
     * Post a user message for generation with body_json
     * @param {Object} inputs - Generation inputs according to model schema
     * @param {Array} attachments - Array of attachment objects {id, name, size, mimetype}
     */
    postUserGenerationMessageForLLM(inputs, attachments = []) {
      const thread = this.thread;

      if (!thread?.id) {
        this.messaging.notify({
          message: this.env._t("Thread not available."),
          type: "danger",
        });
        return;
      }

      const messageBody = inputs.prompt || "Content Generation Request";
      if (!messageBody) {
        this.messaging.notify({
          message: this.env._t("Please enter a message."),
          type: "danger",
        });
        return;
      }

      // Check if the model is configured for generation
      if (!thread.llmModel?.isMediaGenerationModel) {
        this.messaging.notify({
          message: this.env._t(
            "Selected model is not configured for generation."
          ),
          type: "danger",
        });
        return;
      }

      this._reset();

      try {
        // Prepare attachment_ids - just use the raw IDs, not the Many2many format
        const attachment_ids = attachments.length > 0 
          ? attachments.map(att => att.id) // Just the IDs as integers
          : [];

        // Post user message with body_json containing generation inputs
        this.messaging
          .rpc({
            model: "llm.thread",
            method: "message_post",
            args: [thread.id],
            kwargs: {
              body: messageBody,
              body_json: inputs,
              llm_role: "user",
              attachment_ids: attachment_ids,
            },
          })
          .then(() => {
            // After posting user message, trigger generation
            this._startGeneration(thread.id);
          });
      } catch (error) {
        console.error("Error posting generation message:", error);
        this.messaging.notify({
          message:
            this.env._t("Failed to post generation message: ") + String(error),
          type: "danger",
          sticky: true,
        });
      }
    },

    /**
     * Start generation process for the thread
     * @param {Number} threadId - Thread ID
     */
    _startGeneration(threadId) {
      try {
        const url = `/llm/thread/generate?thread_id=${threadId}`;
        console.log("Starting generation for thread:", threadId);

        const eventSource = new EventSource(url);
        this.update({ eventSource });

        eventSource.onmessage = async (event) => {
          try {
            const data = JSON.parse(event.data);
            console.log("Received generation event:", data);

            switch (data.type) {
              case "message_create":
                this._handleMessageCreate(data.message);
                break;
              case "message_chunk":
                this._handleMessageUpdate(data.message);
                break;
              case "message_update":
                this._handleMessageUpdate(data.message);
                break;
              case "error":
                this._closeEventSource();
                this.messaging.notify({
                  message: data.error,
                  type: "danger",
                  sticky: true,
                });
                break;
              case "done":
                const sameThread =
                  this.thread?.id === this.thread?.llmChat?.activeThread?.id;
                if (!sameThread) {
                  this.messaging.notify({
                    message:
                      this.env._t("Generation completed for ") +
                      (this.thread.displayName || "thread"),
                    type: "success",
                  });
                }
                this._closeEventSource();
                break;
              default:
                console.warn("Unknown generation event type:", data.type);
            }
          } catch (parseError) {
            console.error("Error parsing generation event:", parseError);
            this.messaging.notify({
              message: this.env._t("Error processing server response."),
              type: "danger",
            });
          }
        };

        eventSource.onerror = (error) => {
          console.error("EventSource failed:", error);
          this.messaging.notify({
            message: this.env._t(
              "Connection to server lost. Please try again."
            ),
            type: "danger",
            sticky: true,
          });
          this._closeEventSource();
        };
      } catch (error) {
        console.error("Error starting generation:", error);
        this.messaging.notify({
          message: this.env._t("Failed to start generation: ") + String(error),
          type: "danger",
          sticky: true,
        });
      } finally {
        // Focus composer views
        if (this.composerViews) {
          for (const composerView of this.composerViews) {
            composerView.update({ doFocus: true });
          }
        }
      }
    },
  },
});
