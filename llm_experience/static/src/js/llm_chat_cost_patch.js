odoo.define('llm_experience/static/src/js/llm_chat_cost_patch.js', function (require) {
    'use strict';

    require('llm_thread/static/src/models/llm_chat.js');

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;

    const EXPERIENCE_COST_THREAD_FIELDS = [
        'usage_cost_usd_total',
        'usage_cost_currency',
        'usage_billable_accumulated',
    ];

    function formatExperienceCostTooltip(threadData) {
        const name = (threadData.name || '').trim();
        const raw = threadData.usage_cost_usd_total;
        const bill = threadData.usage_billable_accumulated;
        const cur = threadData.usage_cost_currency || 'USD';
        const lines = [];
        if (raw !== undefined && raw !== null && raw !== false) {
            const n = Number(raw);
            if (!Number.isNaN(n)) {
                lines.push('Coste USD acumulado: ' + n.toFixed(6) + ' ' + cur);
            }
        } else {
            lines.push('Coste USD acumulado: —');
        }
        if (name) {
            lines.push(name);
        }
        if (bill !== undefined && bill !== null) {
            lines.push('Tokens acumulados: ' + bill);
        }
        return lines.join('\n');
    }

    registerFieldPatchModel('mail.thread', 'llm_experience/static/src/js/llm_chat_cost_patch.js', {
        usageCostUsdTotal: attr({ default: null }),
        usageCostCurrency: attr({ default: 'USD' }),
        usageBillableAccumulated: attr({ default: null }),
        experienceCostTooltip: attr({ default: '' }),
    });

    registerInstancePatchModel('mail.llm_chat', 'llm_experience/static/src/js/llm_chat_cost_patch.js', {
        async loadThreads(additionalFields, domain) {
            additionalFields = additionalFields || [];
            return this._super(
                additionalFields.concat(EXPERIENCE_COST_THREAD_FIELDS),
                domain
            );
        },

        async refreshThread(threadId, additionalFields) {
            additionalFields = additionalFields || [];
            return this._super(threadId, additionalFields.concat(EXPERIENCE_COST_THREAD_FIELDS));
        },

        _mapThreadDataFromServer: function (threadData) {
            const mapped = this._super(threadData);
            mapped.usageCostUsdTotal = threadData.usage_cost_usd_total !== undefined && threadData.usage_cost_usd_total !== null
                ? threadData.usage_cost_usd_total
                : null;
            mapped.usageCostCurrency = threadData.usage_cost_currency || 'USD';
            mapped.usageBillableAccumulated = threadData.usage_billable_accumulated !== undefined && threadData.usage_billable_accumulated !== null
                ? threadData.usage_billable_accumulated
                : null;
            mapped.experienceCostTooltip = formatExperienceCostTooltip(threadData);
            return mapped;
        },
    });
});
