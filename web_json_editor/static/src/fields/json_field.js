odoo.define('web_json_editor/static/src/fields/json_field.js', function (require) {
    'use strict';

    const AbstractField = require('web.AbstractFieldOwl');
    const fieldRegistry = require('web.field_registry_owl');
    const { onMounted, onWillUnmount } = owl.hooks;

    /**
     * Formatea JSON para modo solo lectura.
     */
    function formatJSON(value) {
        if (!value) {
            return '';
        }
        try {
            const parsed = typeof value === 'string' ? JSON.parse(value) : value;
            return JSON.stringify(parsed, null, 2);
        } catch (e) {
            console.error('Error al formatear JSON:', e);
            return String(value);
        }
    }

    class JsonEditorField extends AbstractField {
        constructor() {
            super(...arguments);
            this.editorRef = owl.hooks.useRef('editor');
            this.editor = null;
            onMounted(() => this._initEditor());
            onWillUnmount(() => this._destroyEditor());
        }

        formatValue() {
            const value = this.value;
            if (!value) {
                return '{}';
            }
            if (typeof value === 'string') {
                try {
                    return formatJSON(JSON.parse(value));
                } catch (e) {
                    return value;
                }
            }
            return formatJSON(value);
        }

        _initEditor() {
            if (!this.editorRef.el || this.mode === 'readonly') {
                return;
            }
            const options = {
                mode: this.mode === 'readonly' ? 'view' : 'code',
                modes: ['code', 'view'],
                search: true,
                history: true,
                navigationBar: true,
                statusBar: true,
                mainMenuBar: true,
                onChange: () => {
                    if (this.mode !== 'readonly') {
                        this._onEditorChange();
                    }
                },
            };
            if (this.nodeOptions) {
                const editorOptions = this.nodeOptions.editor_options || {};
                Object.assign(options, editorOptions);
            }
            if (this.nodeOptions && this.nodeOptions.schema) {
                try {
                    options.schema = typeof this.nodeOptions.schema === 'string'
                        ? JSON.parse(this.nodeOptions.schema)
                        : this.nodeOptions.schema;
                } catch (e) {
                    console.warn('Esquema JSON inválido:', e);
                }
            }
            this.editor = new JSONEditor(this.editorRef.el, options);
            let value = this.value;
            if (!value) {
                value = {};
            } else if (typeof value === 'string') {
                try {
                    value = JSON.parse(value);
                } catch (e) {
                    console.warn('No se pudo analizar la cadena JSON:', e);
                    value = {};
                }
            }
            this.editor.set(value);
        }

        _onEditorChange() {
            if (!this.editor) {
                return;
            }
            const jsonValue = this.editor.get();
            if (this.field.type === 'json') {
                this._setValue(jsonValue);
            } else {
                this._setValue(JSON.stringify(jsonValue));
            }
        }

        _destroyEditor() {
            if (this.editor) {
                this.editor.destroy();
                this.editor = null;
            }
        }
    }

    JsonEditorField.template = 'web_json_editor.JsonEditorField';
    JsonEditorField.supportedFieldTypes = ['text', 'char', 'json'];

    fieldRegistry.add('json_editor', JsonEditorField);

    return JsonEditorField;
});
