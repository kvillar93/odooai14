/** @odoo-module **/

import { attr } from "@mail/model/model_field";
import { clear } from "@mail/model/model_field_command";
import { registerPatch } from "@mail/model/model_core";

registerPatch({
  name: "Composer",
  fields: {
    placeholderLLMChat: attr({
      default: "Ask anything...",
    }),
    isSendDisabled: attr({
      compute() {
        if (this.thread?.model === "llm.thread") {
          const hasText = Boolean(this.textInputContent && this.textInputContent.trim());
          const hasFiles = this.attachments.length > 0;
          if (!hasText && !hasFiles) {
            return true;
          }
          return this.hasUploadingAttachment || Boolean(this.eventSource);
        }
        return !this.canPostMessage;
      },
      default: true,
    }),
    eventSource: attr({
      default: null,
    }),
    isStreaming: attr({
      compute() {
        return this.eventSource !== null;
      },
    }),
  },
  recordMethods: {
    stopLLMThreadLoop() {
      // This should close event source
      this._closeEventSource();
    },

    /**
     * Procesa un stream SSE (text/event-stream) desde fetch POST o GET.
     */
    _dispatchStreamEvent(data) {
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
        case "tool_start":
          this.messaging.llmChat?.update({
            llmAnalyzingToolName: data.tool_name || "…",
          });
          break;
        case "tool_end":
          this.messaging.llmChat?.update({ llmAnalyzingToolName: clear() });
          break;
        case "error":
          this._closeEventSource();
          this.messaging.notify({ message: data.error, type: "danger" });
          break;
        case "done": {
          const llmChat = this.messaging.llmChat;
          const sameThread = llmChat?.activeThread?.id === this.thread?.id;
          if (!sameThread) {
            this.messaging.notify({
              message:
                this.env._t("Generation completed for ") +
                this.thread.displayName,
              type: "success",
            });
          }
          if (llmChat && this.thread?.id) {
            llmChat.refreshThread(this.thread.id).catch(() => {});
          }
          this._closeEventSource();
          break;
        }
      }
    },

    async _consumeSSEFromResponse(response) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const block of parts) {
          const line = block.trim();
          if (!line.startsWith("data: ")) {
            continue;
          }
          const jsonStr = line.slice(6);
          if (jsonStr === "[DONE]") {
            continue;
          }
          try {
            const data = JSON.parse(jsonStr);
            this._dispatchStreamEvent(data);
          } catch (e) {
            console.warn("SSE parse error", e, jsonStr);
          }
        }
      }
    },

    /**
     * Start LLM generation with optional message
     * @param {string|null} messageBody - Optional message body (null/empty for auto-generation with prepended messages)
     * @param {number[]} attachmentIds - IDs de ir.attachment del compositor
     */
    async startGeneration(messageBody = null, attachmentIds = []) {
      // Use llmChat.activeThread as single source of truth
      const llmChat = this.messaging.llmChat;
      const thread = llmChat?.activeThread;

      if (!thread || thread.model !== "llm.thread") {
        console.warn("No active LLM thread for generation");
        return;
      }

      const usePost = attachmentIds && attachmentIds.length > 0;
      const baseUrl = `/llm/thread/generate?thread_id=${thread.id}`;

      try {
        if (usePost) {
          // odoo.csrf_token viene del layout web (session de @web/session no lo incluye).
          const csrfToken =
            (typeof odoo !== "undefined" && odoo.csrf_token) || "";
          const url = `${baseUrl}&csrf_token=${encodeURIComponent(csrfToken)}`;
          const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({
              message: messageBody || "",
              attachment_ids: attachmentIds,
            }),
          });
          if (!response.ok) {
            throw new Error(response.statusText || "POST fallido");
          }
          this.update({ eventSource: { streamReader: true } });
          await this._consumeSSEFromResponse(response);
          this.update({ eventSource: null });
        } else {
          let url = baseUrl;
          if (messageBody) {
            url += `&message=${encodeURIComponent(messageBody)}`;
          }
          const eventSource = new EventSource(url);
          this.update({ eventSource });

          eventSource.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            this._dispatchStreamEvent(data);
          };
          eventSource.onerror = () => {
            console.error("EventSource failed");
            this.messaging.notify({
              message: this.env._t("An unknown error occurred"),
              type: "danger",
            });
            this._closeEventSource();
          };
        }
      } catch (error) {
        console.error("Error sending LLM message:", error);
        this.messaging.notify({
          message: this.env._t("Failed to send message."),
          type: "danger",
        });
        this._closeEventSource();
      } finally {
        for (const composerView of this.composerViews) {
          composerView.update({ doFocus: true });
        }
      }
    },

    async postUserMessageForLLM() {
      const thread = this.thread;

      const messageBody = this.textInputContent.trim();
      const attachmentIds = this.attachments.map((a) => a.id);
      if ((!messageBody && !attachmentIds.length) || !thread) {
        this.messaging.notify({
          message: this.env._t("Escriba un mensaje o adjunte un archivo."),
          type: "danger",
        });
        return;
      }

      this._reset();
      await this.startGeneration(messageBody, attachmentIds);
    },

    _closeEventSource() {
      if (this.eventSource && this.eventSource.close) {
        this.eventSource.close();
      }
      this.update({ eventSource: null });
    },

    _handleMessageCreate(message) {
      const result = this.messaging.models.Message.insert(
        this.messaging.models.Message.convertData(message)
      );
      return result;
    },

    _handleMessageUpdate(message) {
      const result = this.messaging.models.Message.findFromIdentifyingData({
        id: message.id,
      });
      if (result) {
        result.update(this.messaging.models.Message.convertData(message));
      }
      return result;
    },
  },
});
