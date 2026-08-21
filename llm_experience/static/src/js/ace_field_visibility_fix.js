odoo.define('llm_experience/static/src/js/ace_field_visibility_fix.js', function (require) {
    'use strict';

    /**
     * Recalcula métricas de Ace cuando el contenedor pasa de 0 px a visible
     * (pestaña inactiva del notebook). En Odoo 14 el widget vive en web.ace_field.
     */
    var AceField;
    try {
        AceField = require('web.ace_field');
    } catch (_err) {
        return;
    }
    if (AceField && AceField.FieldAce) {
        AceField = AceField.FieldAce;
    }
    if (!AceField || typeof AceField.include !== 'function') {
        return;
    }

    function _llmExpForceAceRefresh(editor) {
        try {
            if (!editor || !editor.renderer) {
                return;
            }
            var renderer = editor.renderer;
            if (renderer.$fontMetrics && typeof renderer.$fontMetrics.checkForSizeChanges === 'function') {
                renderer.$fontMetrics.checkForSizeChanges();
            }
            if (typeof renderer.updateFontSize === 'function') {
                renderer.updateFontSize();
            }
            if (typeof renderer.onResize === 'function') {
                renderer.onResize(true);
            }
            if (typeof editor.resize === 'function') {
                editor.resize(true);
            }
        } catch (_e) {
            /* no propagar */
        }
    }

    AceField.include({
        _llmExpScheduleAceRefresh: function () {
            var editor = this.aceEditor;
            if (!editor) {
                return;
            }
            var self = this;
            if (typeof window !== 'undefined' && window.requestAnimationFrame) {
                window.requestAnimationFrame(function () {
                    _llmExpForceAceRefresh(self.aceEditor);
                });
            } else {
                setTimeout(function () {
                    _llmExpForceAceRefresh(self.aceEditor);
                }, 0);
            }
        },
        _llmExpInstallAceVisibilityFix: function () {
            var el = this.$ace && this.$ace[0];
            if (!el && this.el) {
                el = this.el.querySelector && this.el.querySelector('.ace_editor');
            }
            if (!el && this.$el) {
                el = this.$el.find('.ace_editor')[0];
            }
            this._llmExpScheduleAceRefresh();
            if (!el || typeof ResizeObserver === 'undefined') {
                return;
            }
            var self = this;
            this._llmExpAceResizeObserver = new ResizeObserver(function (entries) {
                for (var i = 0; i < entries.length; i++) {
                    var rect = entries[i].contentRect || {};
                    if (rect.width > 0 && rect.height > 0) {
                        _llmExpForceAceRefresh(self.aceEditor);
                    }
                }
            });
            try {
                this._llmExpAceResizeObserver.observe(el);
            } catch (_err) {
                this._llmExpAceResizeObserver = null;
            }
        },
        _startAce: function () {
            var res = this._super.apply(this, arguments);
            this._llmExpInstallAceVisibilityFix();
            return res;
        },
        destroy: function () {
            if (this._llmExpAceResizeObserver) {
                try {
                    this._llmExpAceResizeObserver.disconnect();
                } catch (_err) {
                    /* silenciado */
                }
                this._llmExpAceResizeObserver = null;
            }
            return this._super.apply(this, arguments);
        },
    });
});
