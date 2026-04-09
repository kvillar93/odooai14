/** @odoo-module **/

import { attr } from "@mail/model/model_field";
import { registerPatch } from "@mail/model/model_core";

const EXPERIENCE_COST_THREAD_FIELDS = [
  "usage_cost_usd_total",
  "usage_cost_currency",
  "usage_billable_accumulated",
];

function formatExperienceCostTooltip(threadData) {
  const name = (threadData.name || "").trim();
  const raw = threadData.usage_cost_usd_total;
  const bill = threadData.usage_billable_accumulated;
  const cur = threadData.usage_cost_currency || "USD";
  const lines = [];
  // Primera línea: coste acumulado (campo usage_cost_usd_total del servidor)
  if (raw !== undefined && raw !== null && raw !== false) {
    const n = Number(raw);
    if (!Number.isNaN(n)) {
      lines.push(`Coste USD acumulado: ${n.toFixed(6)} ${cur}`);
    }
  } else {
    lines.push("Coste USD acumulado: —");
  }
  if (name) {
    lines.push(name);
  }
  if (bill !== undefined && bill !== null) {
    lines.push(`Tokens acumulados: ${bill}`);
  }
  return lines.join("\n");
}

registerPatch({
  name: "LLMChat",
  recordMethods: {
    /**
     * Incluye campos de coste en la carga de hilos (tooltip y seguimiento).
     */
    async loadThreads(additionalFields = [], domain = []) {
      return this._super(
        [...additionalFields, ...EXPERIENCE_COST_THREAD_FIELDS],
        domain
      );
    },
    async refreshThread(threadId, additionalFields = []) {
      return this._super(threadId, [
        ...additionalFields,
        ...EXPERIENCE_COST_THREAD_FIELDS,
      ]);
    },
    _mapThreadDataFromServer(threadData) {
      const mapped = this._super(threadData);
      mapped.usageCostUsdTotal = threadData.usage_cost_usd_total ?? null;
      mapped.usageCostCurrency = threadData.usage_cost_currency || "USD";
      mapped.usageBillableAccumulated =
        threadData.usage_billable_accumulated ?? null;
      mapped.experienceCostTooltip = formatExperienceCostTooltip(threadData);
      return mapped;
    },
  },
});

registerPatch({
  name: "Thread",
  fields: {
    usageCostUsdTotal: attr({ default: null }),
    usageCostCurrency: attr({ default: "USD" }),
    usageBillableAccumulated: attr({ default: null }),
    experienceCostTooltip: attr({ default: "" }),
  },
});
