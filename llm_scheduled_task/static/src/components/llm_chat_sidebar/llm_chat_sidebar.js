odoo.define('llm_scheduled_task/static/src/components/llm_chat_sidebar/llm_chat_sidebar.js', function (require) {
    'use strict';

    const LLMChatSidebar = require('llm_thread/static/src/components/llm_chat_sidebar/llm_chat_sidebar.js');
    const LLMChat = require('llm_thread/static/src/components/llm_chat/llm_chat.js');

    const { useState, onWillStart } = owl.hooks;

    /**
     * Extiende la barra lateral del chat LLM con el botón de tareas programadas.
     */
    class LLMChatSidebarScheduledTask extends LLMChatSidebar {
        constructor(...args) {
            super(...args);
            this._scheduledTaskState = useState({ scheduledTaskCount: 0 });
            const self = this;
            onWillStart(async function () {
                try {
                    const uid = self.env.session.uid;
                    const count = await self.env.services.rpc({
                        model: 'llm.scheduled.task',
                        method: 'search_count',
                        args: [[['user_id', '=', uid]]],
                    });
                    self._scheduledTaskState.scheduledTaskCount = count;
                } catch (e) {
                    console.error('llm_scheduled_task: error al contar tareas', e);
                }
            });
        }

        get scheduledTaskCount() {
            return this._scheduledTaskState.scheduledTaskCount;
        }

        /**
         * Abre la lista de tareas programadas del usuario.
         */
        _onClickViewScheduledTasks(ev) {
            if (ev && ev.stopPropagation) {
                ev.stopPropagation();
            }
            this.env.bus.trigger('do-action', {
                action: 'llm_scheduled_task.action_llm_scheduled_task',
            });
        }
    }

    LLMChatSidebarScheduledTask.template = LLMChatSidebar.template;
    LLMChatSidebarScheduledTask.components = LLMChatSidebar.components;
    LLMChatSidebarScheduledTask.props = LLMChatSidebar.props;

    LLMChat.components = Object.assign({}, LLMChat.components, {
        LLMChatSidebar: LLMChatSidebarScheduledTask,
    });

    return LLMChatSidebarScheduledTask;
});
