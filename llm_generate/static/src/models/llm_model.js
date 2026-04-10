odoo.define('llm_generate/static/src/models/llm_model.js', function (require) {
    'use strict';

    const { registerFieldPatchModel, registerInstancePatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');

    const attr = ModelField.attr;

    registerFieldPatchModel('mail.llm_model', 'llm_generate/static/src/models/llm_model.js', {
        modelUse: attr(),
        details: attr(),
        isMediaGenerationModel: attr({
            compute: '_computeIsMediaGenerationModel',
            dependencies: ['modelUse'],
        }),
        inputSchema: attr({
            compute: '_computeInputSchema',
            dependencies: ['details'],
        }),
        outputSchema: attr({
            compute: '_computeOutputSchema',
            dependencies: ['details'],
        }),
    });

    registerInstancePatchModel('mail.llm_model', 'llm_generate/static/src/models/llm_model.js', {
        _computeIsMediaGenerationModel: function () {
            if (!this.modelUse) {
                return false;
            }
            const generationTypes = ['image_generation', 'generation'];
            return generationTypes.indexOf(this.modelUse) >= 0;
        },

        _computeInputSchema: function () {
            if (!this.details || !this.details.input_schema) {
                return {};
            }
            return this.details.input_schema;
        },

        _computeOutputSchema: function () {
            if (!this.details || !this.details.output_schema) {
                return {};
            }
            return this.details.output_schema;
        },
    });
});
