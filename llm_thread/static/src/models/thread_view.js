odoo.define('llm_thread/static/src/models/thread_view.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const one2one = ModelField.one2one;

    registerFieldPatchModel('mail.thread_view', 'llm_thread/static/src/models/thread_view.js', {
        llmChatThreadHeaderView: one2one('mail.llm_chat_thread_header_view', {
            inverse: 'threadView',
            isCausal: true,
        }),
    });

    registerInstancePatchModel('mail.thread_view', 'llm_thread/static/src/models/thread_view.js', {
        _created() {
            this._super.apply(this, arguments);
            if (this.thread && this.thread.model === 'llm.thread' && !this.llmChatThreadHeaderView) {
                this.update({ llmChatThreadHeaderView: [['create', {}]] });
            }
        },

        _shouldMessageBeSquashed(prevMessage, message) {
            if (prevMessage !== undefined && message !== undefined) {
                if (
                    prevMessage.llmRole !== undefined &&
                    message.llmRole !== undefined
                ) {
                    if (prevMessage.llmRole !== message.llmRole) {
                        return false;
                    }
                }
            }
            return this._super.apply(this, arguments);
        },
    });
});
