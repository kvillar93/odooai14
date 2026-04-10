odoo.define('llm_thread/static/src/models/thread_viewer_llm.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const many2one = ModelField.many2one;
    const one2one = ModelField.one2one;

    registerFieldPatchModel('mail.thread_viewer', 'llm_thread/static/src/models/thread_viewer_llm.js', {
        llmChatView: one2one('mail.llm_chat_view', {
            inverse: 'threadViewer',
        }),
        llmChatViewThread: many2one('mail.thread', {
            related: 'llmChatView.thread',
        }),
        hasThreadView: attr({
            dependencies: [
                'chatterHasThreadView',
                'chatWindowHasThreadView',
                'discussHasThreadView',
                'llmChatView',
            ],
        }),
        thread: many2one('mail.thread', {
            dependencies: [
                'chatterThread',
                'chatWindowThread',
                'discussThread',
                'llmChatViewThread',
            ],
        }),
    });

    registerInstancePatchModel('mail.thread_viewer', 'llm_thread/static/src/models/thread_viewer_llm.js', {
        _computeHasThreadView() {
            if (this.llmChatView) {
                return true;
            }
            return this._super.apply(this, arguments);
        },

        _computeStringifiedDomain() {
            if (this.llmChatView) {
                return '[]';
            }
            return this._super.apply(this, arguments);
        },

        _computeThread() {
            if (this.llmChatView) {
                var t = this.llmChatView.thread;
                if (!t) {
                    return [['unlink']];
                }
                return [['link', t]];
            }
            return this._super.apply(this, arguments);
        },
    });
});
