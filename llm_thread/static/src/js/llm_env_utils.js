odoo.define('llm_thread/static/src/js/llm_env_utils.js', function (require) {
    'use strict';

    /**
     * RPC compatible con Odoo 14 (env.services.rpc).
     */
    function llmRpc(env, params) {
        return env.services.rpc(params);
    }

    /**
     * Notificación backend.
     */
    function llmNotify(env, payload) {
        const notif = env.services.notification;
        if (notif && notif.notify) {
            notif.notify(payload);
        }
    }

    /**
     * Espera a que mail.messaging esté creado e inicializado.
     */
    function waitMessagingReady(env) {
        return new Promise(function (resolve) {
            function check() {
                if (env.messaging && env.messaging.isInitialized) {
                    resolve();
                    return;
                }
                setTimeout(check, 30);
            }
            env.messagingCreatedPromise.then(function () {
                if (env.messaging && env.messaging.isInitialized) {
                    resolve();
                } else {
                    check();
                }
            });
        });
    }

    return {
        llmRpc: llmRpc,
        llmNotify: llmNotify,
        waitMessagingReady: waitMessagingReady,
    };
});
