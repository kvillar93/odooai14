odoo.define('llm_thread/static/src/client_actions/open_chatter_action.js', function (require) {
    'use strict';

    const core = require('web.core');

    const SESSION_STORAGE_KEY = 'llm_pending_open_in_chatter';

    function getPendingOpenInChatter() {
        try {
            const data = sessionStorage.getItem(SESSION_STORAGE_KEY);
            if (!data) {
                return null;
            }
            const state = JSON.parse(data);
            if (Date.now() - state.timestamp > 30000) {
                sessionStorage.removeItem(SESSION_STORAGE_KEY);
                return null;
            }
            return state;
        } catch (e) {
            console.error('[LLM] No se pudo leer el estado pendiente:', e);
            return null;
        }
    }

    function consumePendingOpenInChatter(model, resId) {
        const pending = getPendingOpenInChatter();
        if (!pending) {
            return null;
        }
        if (pending.model === model && pending.resId === resId) {
            sessionStorage.removeItem(SESSION_STORAGE_KEY);
            return pending;
        }
        return null;
    }

    function clearPendingOpenInChatter() {
        sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }

    function openChatterAction(parent, action) {
        const params = action.params || {};
        const thread_id = params.thread_id;
        const model = params.model;
        const res_id = params.res_id;

        if (!thread_id || !model || !res_id) {
            console.error('[LLM] open_chatter_action: faltan parámetros', action.params);
            return;
        }

        const pendingState = {
            threadId: thread_id,
            model: model,
            resId: res_id,
            autoGenerate: true,
            timestamp: Date.now(),
        };

        try {
            sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(pendingState));
        } catch (e) {
            console.error('[LLM] No se pudo guardar el estado en sessionStorage:', e);
        }

        return {
            type: 'ir.actions.act_window',
            res_model: model,
            res_id: res_id,
            views: [[false, 'form']],
            target: 'current',
        };
    }

    core.action_registry.add('llm_open_chatter', openChatterAction);

    return {
        getPendingOpenInChatter: getPendingOpenInChatter,
        consumePendingOpenInChatter: consumePendingOpenInChatter,
        clearPendingOpenInChatter: clearPendingOpenInChatter,
    };
});
