odoo.define('llm_generate/static/src/components/llm_media_form/llm_form_fields_view.js', function (require) {
    'use strict';

    const { Component } = owl;

    class LLMFormFieldsView extends Component {}

    LLMFormFieldsView.template = 'llm_generate.LLMFormFieldsView';
    LLMFormFieldsView.props = {
        state: { type: Object, optional: false },
        inputSchema: { type: Object, optional: true },
        formFields: { type: Array, optional: false },
        requiredFields: { type: Array, optional: false },
        optionalFields: { type: Array, optional: false },
        onInputChange: { type: Function, optional: false },
        toggleAdvancedSettings: { type: Function, optional: false },
    };

    return LLMFormFieldsView;
});
