odoo.define('llm_thread/static/src/models/message.js', function (require) {
    'use strict';

    const { registerClassPatchModel, registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;
    const llmUi = require('llm_thread/static/src/js/llm_ui_utils.js');

    registerClassPatchModel('mail.message', 'llm_thread/static/src/models/message.js', {
        convertData(data) {
            if ('channel_ids' in data && data.channel_ids && !Array.isArray(data.channel_ids)) {
                data = Object.assign({}, data, { channel_ids: [] });
            }
            // ``record_name`` es el nombre del hilo cuando se creó el mensaje: si
            // llega, pisa el título actual del chat con uno antiguo («New Chat #N»).
            if (data.model === 'llm.thread' && 'record_name' in data) {
                data = Object.assign({}, data);
                delete data.record_name;
            }
            const data2 = this._super.apply(this, [data]);
            if ('user_vote' in data) {
                data2.user_vote = data.user_vote;
            }
            if ('llm_role' in data) {
                data2.llmRole = data.llm_role;
            }
            if ('body_json' in data) {
                var bj = data.body_json;
                if (typeof bj === 'string' && bj) {
                    try { bj = JSON.parse(bj); } catch (e) { bj = null; }
                }
                data2.bodyJson = bj || null;
            }
            return data2;
        },
    });

    registerFieldPatchModel('mail.message', 'llm_thread/static/src/models/message.js', {
        user_vote: attr({
            default: 0,
        }),
        llmRole: attr({
            default: null,
        }),
        bodyJson: attr({
            default: null,
        }),
        toolData: attr({
            compute: '_computeToolData',
            dependencies: ['llmRole', 'bodyJson'],
        }),
        toolCallId: attr({
            compute: '_computeToolCallId',
            dependencies: ['toolData'],
        }),
        toolCallDefinitionFormatted: attr({
            compute: '_computeToolCallDefinitionFormatted',
            dependencies: ['toolData'],
        }),
        toolCallResultData: attr({
            compute: '_computeToolCallResultData',
            dependencies: ['toolData'],
        }),
        toolCallResultIsError: attr({
            compute: '_computeToolCallResultIsError',
            dependencies: ['toolData'],
        }),
        toolCallResultFormatted: attr({
            compute: '_computeToolCallResultFormatted',
            dependencies: ['toolCallResultData'],
        }),
        toolName: attr({
            compute: '_computeToolName',
            dependencies: ['toolData'],
        }),
        toolCalls: attr({
            compute: '_computeToolCalls',
            dependencies: ['toolData'],
        }),
        llmThinking: attr({
            compute: '_computeLlmThinking',
            dependencies: ['llmRole', 'bodyJson'],
        }),
        llmThinkingHtml: attr({
            compute: '_computeLlmThinkingHtml',
            dependencies: ['llmThinking'],
        }),
        llmThinkingActive: attr({
            compute: '_computeLlmThinkingActive',
            dependencies: ['bodyJson'],
        }),
        llmThinkingLabel: attr({
            compute: '_computeLlmThinkingLabel',
            dependencies: ['llmThinking', 'llmThinkingActive', 'bodyJson'],
        }),
        llmIsToolCallOnly: attr({
            compute: '_computeLlmIsToolCallOnly',
            dependencies: ['llmRole', 'toolCalls', 'body'],
        }),
        llmToolStep: attr({
            compute: '_computeLlmToolStep',
            dependencies: ['llmRole', 'toolData'],
        }),
        llmToolArgsFormatted: attr({
            compute: '_computeLlmToolArgsFormatted',
            dependencies: ['toolData'],
        }),
        llmMetaLine: attr({
            compute: '_computeLlmMetaLine',
            dependencies: ['llmRole', 'llmIsToolCallOnly', 'bodyJson'],
        }),
        /** Clase de presentación: tool | hidden | thinkingOnly | contextNote | assistant. */
        llmKind: attr({
            compute: '_computeLlmKind',
            dependencies: ['llmRole', 'llmIsToolCallOnly', 'llmThinking', 'body'],
        }),
        isEmpty: attr({
            dependencies: [
                'attachments',
                'body',
                'subtype_description',
                'tracking_value_ids',
                'bodyJson',
            ],
        }),
    });

    registerInstancePatchModel('mail.message', 'llm_thread/static/src/models/message.js', {
        _computeIsEmpty() {
            if (this.bodyJson) {
                return false;
            }
            return this._super.apply(this, arguments);
        },

        _computeLlmThinking() {
            var data = this.bodyJson;
            return (this.llmRole === 'assistant' && data && data.thinking) || '';
        },

        _computeLlmThinkingHtml() {
            return this.llmThinking ? llmUi.thinkingToHtml(this.llmThinking) : '';
        },

        _computeLlmThinkingActive() {
            return Boolean(this.bodyJson && this.bodyJson.thinking_active);
        },

        _computeLlmThinkingLabel() {
            if (!this.llmThinking) {
                return '';
            }
            if (this.llmThinkingActive) {
                return llmUi.thinkingHeadline(this.llmThinking) || 'Pensando…';
            }
            var ms = this.bodyJson && this.bodyJson.thinking_ms;
            return ms ? 'Pensó durante ' + llmUi.formatDuration(ms) : 'Razonamiento';
        },

        _computeLlmIsToolCallOnly() {
            if (this.llmRole !== 'assistant' || !(this.toolCalls && this.toolCalls.length)) {
                return false;
            }
            return !String(this.body || '').replace(/<[^>]*>/g, '').trim();
        },

        _computeLlmToolStep() {
            if (this.llmRole !== 'tool') {
                return null;
            }
            var data = this.toolData || {};
            var call = data.tool_call || {};
            var rawArgs = data.arguments || (call.function && call.function.arguments);
            var step = llmUi.describeToolStep(data.tool_name, rawArgs, data.status, data.result);
            step.duration = data.duration_ms ? llmUi.formatDuration(data.duration_ms) : '';
            step.running = data.status === 'requested' || data.status === 'executing';
            step.error = data.status === 'error' ? String(data.error || '') : '';
            return step;
        },

        _computeLlmToolArgsFormatted() {
            var data = this.toolData || {};
            var call = data.tool_call || {};
            var raw = data.arguments || (call.function && call.function.arguments);
            if (!raw) {
                return '{}';
            }
            try {
                return JSON.stringify(typeof raw === 'string' ? JSON.parse(raw) : raw, null, 2);
            } catch (e) {
                return String(raw);
            }
        },

        _computeLlmMetaLine() {
            if (this.llmRole !== 'assistant' || this.llmIsToolCallOnly) {
                return '';
            }
            return llmUi.responseMetaLine(this.bodyJson);
        },

        _computeLlmKind() {
            if (this.llmRole === 'tool') {
                return 'tool';
            }
            if (this.llmRole === 'assistant') {
                if (this.llmIsToolCallOnly) {
                    return this.llmThinking ? 'thinkingOnly' : 'hidden';
                }
                return 'assistant';
            }
            if (!this.llmRole && llmUi.isContextNoteBody(this.body)) {
                return 'contextNote';
            }
            return '';
        },

        _computeToolData() {
            if (['tool', 'assistant'].indexOf(this.llmRole) >= 0 && this.bodyJson) {
                var val = this.bodyJson;
                if (typeof val === 'string') {
                    try { val = JSON.parse(val); } catch (e) { return null; }
                }
                return (typeof val === 'object' && val !== null) ? val : null;
            }
            return null;
        },

        _computeToolCallId() {
            const toolData = this.toolData;
            return toolData && toolData.tool_call_id ? toolData.tool_call_id : null;
        },

        _computeToolCallDefinitionFormatted() {
            const toolData = this.toolData;
            return toolData && toolData.tool_call ? toolData.tool_call : null;
        },

        _computeToolCallResultData() {
            const toolData = this.toolData;
            if (toolData) {
                if ('result' in toolData) {
                    return toolData.result;
                }
                if ('error' in toolData) {
                    return { error: toolData.error };
                }
            }
            return null;
        },

        _computeToolCallResultIsError() {
            const toolData = this.toolData;
            return Boolean(toolData && toolData.status === 'error');
        },

        _computeToolCallResultFormatted() {
            const resultData = this.toolCallResultData;
            if (resultData === undefined || resultData === null) {
                return '';
            }
            try {
                return typeof resultData === 'object'
                    ? JSON.stringify(resultData, null, 2)
                    : String(resultData);
            } catch (e) {
                console.error('Error formatting tool call result:', e);
                return String(resultData);
            }
        },

        _computeToolName() {
            const toolData = this.toolData;
            return toolData && toolData.tool_name ? toolData.tool_name : null;
        },

        _computeToolCalls() {
            const toolData = this.toolData;
            return toolData && toolData.tool_calls ? toolData.tool_calls : [];
        },
    });
});
