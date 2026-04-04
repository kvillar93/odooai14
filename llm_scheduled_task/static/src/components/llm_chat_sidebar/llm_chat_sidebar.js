/** @odoo-module **/

import { LLMChatSidebar } from "@llm_thread/components/llm_chat_sidebar/llm_chat_sidebar";
import { patch } from "@web/core/utils/patch";
import { onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(LLMChatSidebar.prototype, "llm_scheduled_task.LLMChatSidebar", {
  setup() {
    this._super(...arguments);
    this.orm = useService("orm");
    this.state = useState({ scheduledTaskCount: 0 });
    onWillStart(async () => {
      try {
        const uid = this.env.services.user.userId;
        const count = await this.orm.searchCount("llm.scheduled.task", [
          ["user_id", "=", uid],
        ]);
        this.state.scheduledTaskCount = count;
      } catch (e) {
        console.error("llm_scheduled_task: error al contar tareas", e);
      }
    });
  },

  get scheduledTaskCount() {
    return this.state.scheduledTaskCount;
  },

  /**
   * Abre la lista de tareas programadas del usuario (ejecuciones, cancelar, editar prompt).
   */
  _onClickViewScheduledTasks(ev) {
    ev?.stopPropagation?.();
    this.env.services.action.doAction(
      "llm_scheduled_task.action_llm_scheduled_task"
    );
  },
});
