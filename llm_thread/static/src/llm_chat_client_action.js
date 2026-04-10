odoo.define('llm_thread/static/src/llm_chat_client_action.js', function (require) {
    'use strict';

    const AbstractAction = require('web.AbstractAction');
    const core = require('web.core');
    const { Component } = owl;
    const LLMChatContainer = require('llm_thread/static/src/components/llm_chat_container/llm_chat_container.js');

    const LLMChatClientAction = AbstractAction.extend({
        template: 'llm_thread.LLMChatClientAction',
        hasControlPanel: false,

        init: function (parent, action, options) {
            this._super.apply(this, arguments);
            // AbstractAction no guarda el descriptor; hace falta para props y active_id.
            this.action = action || {};
            this.component = undefined;
        },

        willStart: async function () {
            await this._super.apply(this, arguments);
            this.env = Component.env;
            await this.env.messagingCreatedPromise;
        },

        destroy: function () {
            if (this.component) {
                this.component.destroy();
                this.component = undefined;
            }
            this._super.apply(this, arguments);
        },

        on_attach_callback: function () {
            if (this.component) {
                return;
            }
            // OWL 1: el padre no puede ser un Widget legacy (p. ej. Discuss usa `new DiscussComponent()`).
            this.component = new LLMChatContainer(null, {
                action: this.action,
                actionId: this.action.id,
                className: 'o_LLMChatClientAction_inner h-100',
            });
            return this.component.mount(this.el);
        },

        on_detach_callback: function () {
            if (this.component) {
                this.component.destroy();
                this.component = undefined;
            }
        },
    });

    core.action_registry.add('llm_thread.chat_client_action', LLMChatClientAction);
});
