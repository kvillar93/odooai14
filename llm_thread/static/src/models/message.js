odoo.define('llm_thread/static/src/models/message.js', function (require) {
    'use strict';

    const { registerClassPatchModel, registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;

    registerClassPatchModel('mail.message', 'llm_thread/static/src/models/message.js', {
        convertData(data) {
            if ('channel_ids' in data && data.channel_ids && !Array.isArray(data.channel_ids)) {
                data = Object.assign({}, data, { channel_ids: [] });
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
