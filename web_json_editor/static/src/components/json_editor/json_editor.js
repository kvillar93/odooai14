odoo.define('web_json_editor/static/src/components/json_editor/json_editor.js', function (require) {
    'use strict';

    const { Component } = owl;
    const { onMounted, onWillUnmount, onPatched } = owl.hooks;

    /**
     * Componente genérico de edición JSON (OWL 1).
     */
    class JsonEditorComponent extends Component {
        constructor() {
            super(...arguments);
            this.editorRef = owl.hooks.useRef('editor');
            this.editor = null;
            this._lastSyncedValue = undefined;

            onMounted(() => this._initEditor());
            onWillUnmount(() => this._destroyEditor());

            onPatched(() => {
                if (!this.editor || this.props.value === undefined) {
                    return;
                }
                try {
                    const currentValue = this.editor.get();
                    if (JSON.stringify(currentValue) !== JSON.stringify(this.props.value)) {
                        this.setValue(this.props.value);
                    }
                } catch (e) {
                    this.setValue(this.props.value);
                }
                if (this.props.schema && this.editor) {
                    this.updateSchema(this.props.schema);
                }
            });
        }

        _initEditor() {
            if (!this.editorRef.el) {
                return;
            }
            const mode = this.props.mode || 'code';
            const options = {
                mode: mode,
                modes: this.props.modes || [mode],
                search: this.props.search !== false,
                history: this.props.history !== false,
                indentation: this.props.indentation || 2,
                mainMenuBar: this.props.mainMenuBar !== false,
                navigationBar: this.props.navigationBar !== false,
                statusBar: this.props.statusBar !== false,
                colorPicker: this.props.colorPicker !== false,
                onChange: () => this.handleChange(),
                onValidationError: (errors) => this.handleValidationError(errors),
                onError: (error) => {
                    if (this.props.onError) {
                        this.props.onError(error);
                    }
                },
                allowSchemaSuggestions: this.props.allowSchemaSuggestions !== false,
            };
            if (this.props.schema) {
                options.schema = this.props.schema;
                options.schemaRefs = this.props.schemaRefs;
            }
            if (this.props.autocomplete) {
                options.autocomplete = this.props.autocomplete;
            } else if (this.props.schema) {
                options.autocomplete = this.generateAutocompleteOptions();
            }
            this.editor = new JSONEditor(this.editorRef.el, options);
            if (this.props.value) {
                this.setValue(this.props.value);
            }
        }

        handleChange() {
            if (!this.props.onChange) {
                return;
            }
            try {
                this.editor.validate().then((errors) => {
                    if (errors && errors.length > 0) {
                        if (this.props.onValidationError) {
                            this.props.onValidationError(errors);
                        }
                        let textValue = '';
                        if (this.editor && typeof this.editor.getText === 'function') {
                            textValue = this.editor.getText();
                        }
                        let jsonValue = null;
                        try {
                            jsonValue = this.editor.get();
                        } catch (e) {
                            // JSON inválido
                        }
                        this.props.onChange({
                            value: jsonValue || textValue,
                            isValid: false,
                            error: 'Falló la validación del esquema',
                            text: textValue,
                            validationErrors: errors,
                        });
                    } else {
                        const json = this.editor.get();
                        this.props.onChange({
                            value: json,
                            isValid: true,
                            text: this.editor.getText(),
                        });
                    }
                });
            } catch (e) {
                let textValue = '';
                if (this.editor && typeof this.editor.getText === 'function') {
                    textValue = this.editor.getText();
                }
                this.props.onChange({
                    value: textValue,
                    isValid: false,
                    error: e.message,
                    text: textValue,
                });
            }
        }

        handleValidationError(errors) {
            if (this.props.onValidationError) {
                this.props.onValidationError(errors);
            }
        }

        updateSchema(schema) {
            if (!this.editor || !schema) {
                return;
            }
            try {
                this.editor.setSchema(schema, this.props.schemaRefs);
            } catch (e) {
                console.error('Error al establecer el esquema JSON:', e);
                if (this.props.onError) {
                    this.props.onError(e);
                }
            }
        }

        generateAutocompleteOptions() {
            if (!this.props.schema) {
                return {};
            }
            const schema = this.props.schema;
            return {
                filter: 'start',
                trigger: 'key',
                getOptions: function (text, path, input, editor) {
                    if (path.length === 0 && schema.properties && input === 'field') {
                        return Object.keys(schema.properties).map((key) => {
                            const prop = schema.properties[key];
                            const description = prop.description || key;
                            return {
                                text: key,
                                value: key,
                                title: description,
                            };
                        });
                    }
                    if (path.length > 0 && input === 'value') {
                        let currentSchema = schema;
                        for (const segment of path) {
                            if (currentSchema.properties && currentSchema.properties[segment]) {
                                currentSchema = currentSchema.properties[segment];
                            } else if (currentSchema.items) {
                                currentSchema = currentSchema.items;
                            } else {
                                currentSchema = null;
                                break;
                            }
                        }
                        if (currentSchema && currentSchema.enum) {
                            return currentSchema.enum.map((value) => {
                                const valueStr = typeof value === 'string' ? `"${value}"` : String(value);
                                return { text: valueStr, value: valueStr, title: valueStr };
                            });
                        }
                        if (currentSchema && currentSchema.examples && currentSchema.examples.length) {
                            return currentSchema.examples.map((value) => {
                                const valueStr = typeof value === 'string' ? `"${value}"` : String(value);
                                return { text: valueStr, value: valueStr, title: `Ejemplo: ${valueStr}` };
                            });
                        }
                    }
                    return null;
                },
            };
        }

        setValue(value) {
            if (!this.editor) {
                return;
            }
            try {
                if (typeof value === 'string') {
                    this.editor.setText(value);
                } else {
                    this.editor.set(value);
                }
            } catch (e) {
                console.error('Error al establecer el valor JSON:', e);
                if (this.props.onError) {
                    this.props.onError(e);
                }
            }
        }

        validate() {
            if (!this.editor) {
                return Promise.resolve([]);
            }
            return this.editor.validate();
        }

        getValue() {
            if (!this.editor) {
                return null;
            }
            return this.editor.get();
        }

        getTextValue() {
            if (!this.editor) {
                return '';
            }
            return this.editor.getText();
        }

        focus() {
            if (this.editor) {
                this.editor.focus();
            }
        }

        _destroyEditor() {
            if (this.editor) {
                this.editor.destroy();
                this.editor = null;
            }
        }
    }

    JsonEditorComponent.template = 'web_json_editor.JsonEditorComponent';
    JsonEditorComponent.props = {
        value: { type: [Object, String], optional: true },
        onChange: { type: Function, optional: true },
        onError: { type: Function, optional: true },
        onValidationError: { type: Function, optional: true },
        height: { type: String, optional: true, default: '400px' },
        mode: { type: String, optional: true, default: 'code' },
        modes: { type: Array, optional: true },
        schema: { type: Object, optional: true },
        schemaRefs: { type: Object, optional: true },
        search: { type: Boolean, optional: true, default: true },
        history: { type: Boolean, optional: true, default: true },
        indentation: { type: Number, optional: true, default: 2 },
        mainMenuBar: { type: Boolean, optional: true, default: true },
        navigationBar: { type: Boolean, optional: true, default: true },
        statusBar: { type: Boolean, optional: true, default: true },
        colorPicker: { type: Boolean, optional: true, default: true },
        allowSchemaSuggestions: { type: Boolean, optional: true, default: true },
        autocomplete: { type: Object, optional: true },
    };

    return JsonEditorComponent;
});
