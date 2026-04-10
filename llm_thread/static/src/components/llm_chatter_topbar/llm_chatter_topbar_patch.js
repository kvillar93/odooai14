odoo.define('llm_thread/static/src/components/llm_chatter_topbar/llm_chatter_topbar_patch.js', function (require) {
    'use strict';

    const ChatterTopbar = require('mail/static/src/components/chatter_topbar/chatter_topbar.js');

    const _onClickSendMessage = ChatterTopbar.prototype._onClickSendMessage;
    const _onClickLogNote = ChatterTopbar.prototype._onClickLogNote;
    const _onClickScheduleActivity = ChatterTopbar.prototype._onClickScheduleActivity;
    const _onClickAttachments = ChatterTopbar.prototype._onClickAttachments;

    ChatterTopbar.prototype._onClickToggleLLMChat = function (ev) {
        if (this.chatter) {
            this.chatter.toggleLLMChat();
        }
    };

    ChatterTopbar.prototype._onClickSendMessage = function (ev) {
        if (this.chatter && this.chatter.is_chatting_with_llm) {
            this.chatter.toggleLLMChat();
        }
        return _onClickSendMessage.call(this, ev);
    };

    ChatterTopbar.prototype._onClickLogNote = function (ev) {
        if (this.chatter && this.chatter.is_chatting_with_llm) {
            this.chatter.toggleLLMChat();
        }
        return _onClickLogNote.call(this, ev);
    };

    ChatterTopbar.prototype._onClickScheduleActivity = function (ev) {
        if (this.chatter && this.chatter.is_chatting_with_llm) {
            this.chatter.toggleLLMChat();
        }
        return _onClickScheduleActivity.call(this, ev);
    };

    ChatterTopbar.prototype._onClickAttachments = function (ev) {
        if (this.chatter && this.chatter.is_chatting_with_llm) {
            this.chatter.toggleLLMChat();
        }
        return _onClickAttachments.call(this, ev);
    };

    return ChatterTopbar;
});
