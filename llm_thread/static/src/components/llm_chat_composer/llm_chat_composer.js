/** @odoo-module **/

import { registerMessagingComponent } from "@mail/utils/messaging_component";
import { useComponentToModel } from "@mail/component_hooks/use_component_to_model";
import { Component, useState } from "@odoo/owl";

export class LLMChatComposer extends Component {
  /**
   * @override
   */
  setup() {
    super.setup();
    useComponentToModel({ fieldName: "component" });
    this.state = useState({
      isRecording: false,
      hasVoiceAPI:
        typeof navigator !== "undefined" &&
        Boolean(navigator.mediaDevices?.getUserMedia),
    });
    this._mediaRecorder = null;
    this._audioChunks = [];
  }

  /**
   * @returns {ComposerView}
   */
  get composerView() {
    return this.props.record;
  }

  /**
   * @returns {Boolean}
   */
  get isDisabled() {
    // Read the computed disabled state from the model.
    return this.composerView.composer.isSendDisabled;
  }

  get isStreaming() {
    return this.composerView.composer.isStreaming;
  }

  get messaging() {
    return this.composerView.messaging;
  }

  // --------------------------------------------------------------------------
  // Private
  // --------------------------------------------------------------------------

  /**
   * Intercept send button click
   * @private
   */
  _onClickSend() {
    if (this.isDisabled) {
      return;
    }

    this.composerView.composer.postUserMessageForLLM();
  }

  /**
   * Handles click on the stop button.
   *
   * @private
   */
  _onClickStop() {
    this.composerView.composer.stopLLMThreadLoop();
  }

  async onClickVoiceRecording() {
    if (!this.state.hasVoiceAPI) {
      return;
    }
    if (this.state.isRecording) {
      this._stopVoiceRecording();
    } else {
      await this._startVoiceRecording();
    }
  }

  async _startVoiceRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this._audioChunks = [];
      let mimeType;
      if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
        mimeType = "audio/webm;codecs=opus";
      } else if (MediaRecorder.isTypeSupported("audio/webm")) {
        mimeType = "audio/webm";
      }
      this._mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      this._mediaRecorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) {
          this._audioChunks.push(ev.data);
        }
      };
      this._mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(this._audioChunks, {
          type: this._mediaRecorder.mimeType || "audio/webm",
        });
        const ext = blob.type.includes("webm")
          ? "webm"
          : blob.type.includes("ogg")
            ? "ogg"
            : "bin";
        const file = new File(
          [blob],
          `nota-de-voz-${Date.now()}.${ext}`,
          { type: blob.type || "audio/webm" }
        );
        this.composerView.fileUploader.uploadFiles([file]);
        this.state.isRecording = false;
        this._mediaRecorder = null;
        this._audioChunks = [];
      };
      this._mediaRecorder.start();
      this.state.isRecording = true;
    } catch (e) {
      console.warn("Voice recording error", e);
      this.messaging.notify({
        message: this.env._t(
          "No se pudo acceder al micrófono. Compruebe los permisos del navegador."
        ),
        type: "warning",
      });
    }
  }

  _stopVoiceRecording() {
    if (this._mediaRecorder && this.state.isRecording) {
      try {
        this._mediaRecorder.stop();
      } catch (e) {
        this.state.isRecording = false;
      }
    }
  }
}

Object.assign(LLMChatComposer, {
  props: { record: Object },
  template: "llm_thread.LLMChatComposer",
});

registerMessagingComponent(LLMChatComposer);
