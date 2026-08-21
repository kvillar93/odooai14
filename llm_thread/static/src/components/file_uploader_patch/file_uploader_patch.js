odoo.define('llm_thread/static/src/components/file_uploader_patch/file_uploader_patch.js', function (require) {
    'use strict';

    /**
     * Parche para FileUploader._performUpload
     *
     * El mecanismo estándar de Odoo usa: fetch → eval(script) → jQuery.trigger → handler.
     * Esa cadena puede fallar silenciosamente en ciertos contextos (panel flotante, etc.)
     * porque depende de window.eval y un evento jQuery global.
     *
     * Este parche reemplaza ese flujo por uno más robusto:
     * fetch → parsear respuesta JSON → insertar adjunto directamente.
     */

    var FileUploader = require('mail/static/src/components/file_uploader/file_uploader.js');

    var _RE_TRIGGER_DATA = /\.trigger\(\s*[^,]+,\s*(\[[\s\S]*\])\s*\)/;

    /**
     * Extrae el array JSON de datos de adjuntos de la respuesta HTML del servidor.
     * La respuesta tiene la forma:
     *   <script>var win=window.top.window;win.jQuery(win).trigger('cb',[{...}]);</script>
     *
     * @param {string} html - Texto de respuesta del servidor
     * @returns {Array|null} - Array de objetos de datos o null si no se pudo parsear
     */
    function _extractAttachmentData(html) {
        var m = _RE_TRIGGER_DATA.exec(html);
        if (!m) {
            return null;
        }
        try {
            return JSON.parse(m[1]);
        } catch (_e) {
            return null;
        }
    }

    FileUploader.prototype._performUpload = async function (files) {
        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var uploadingAttachment = this.env.models['mail.attachment'].find(function (att) {
                return att.isTemporary && att.filename === file.name;
            });
            if (!uploadingAttachment) {
                continue;
            }
            try {
                var response = await this.env.browser.fetch('/web/binary/upload_attachment', {
                    method: 'POST',
                    body: this._createFormData(file),
                    signal: uploadingAttachment.uploadingAbortController.signal,
                });
                var html = await response.text();
                var filesData = _extractAttachmentData(html);
                if (filesData) {
                    for (var j = 0; j < filesData.length; j++) {
                        var fd = filesData[j];
                        if (fd.error || !fd.id) {
                            this.env.services['notification'].notify({
                                type: 'danger',
                                message: fd.error || 'Error al subir adjunto',
                            });
                            continue;
                        }
                        await new Promise(function (resolve) { setTimeout(resolve); });
                        var attachment = this.env.models['mail.attachment'].insert(
                            Object.assign(
                                {
                                    filename: fd.filename,
                                    id: fd.id,
                                    mimetype: fd.mimetype,
                                    name: fd.name,
                                    size: fd.size,
                                },
                                this.props.newAttachmentExtraData
                            )
                        );
                        this.trigger('o-attachment-created', { attachment: attachment });
                    }
                } else {
                    console.warn('[LLM FileUploader] No se pudo parsear respuesta, usando fallback eval:', html.substring(0, 200));
                    var template = document.createElement('template');
                    template.innerHTML = html.trim();
                    if (template.content.firstChild) {
                        window.eval(template.content.firstChild.textContent);
                    }
                }
            } catch (e) {
                if (e.name !== 'AbortError') {
                    console.error('[LLM FileUploader] Error en upload:', e);
                    this.env.services['notification'].notify({
                        type: 'danger',
                        message: 'Error al subir el archivo: ' + (e.message || String(e)),
                    });
                    if (uploadingAttachment) {
                        uploadingAttachment.delete();
                    }
                }
            }
        }
    };

    return FileUploader;
});
