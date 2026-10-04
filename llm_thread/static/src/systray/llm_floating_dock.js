odoo.define('llm_thread/static/src/systray/llm_floating_dock.js', function (require) {
    'use strict';

    /**
     * Chat IA flotante independiente (Odoo 14 / OWL 1).
     *
     * No usa el singleton ``messaging.llmChat`` del chat grande: cada pestaña
     * tiene su propio estado y su propio stream SSE, por lo que el popup puede
     * estar abierto a la vez que la app de chat y con varias conversaciones.
     */

    const core = require('web.core');
    const session = require('web.session');
    const Message = require('mail/static/src/components/message/message.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');
    const llmUi = require('llm_thread/static/src/js/llm_ui_utils.js');

    const { Component } = owl;
    const { onMounted, onPatched, onWillUnmount, useRef, useState } = owl.hooks;

    const PAGE_SIZE = 60;
    const VISIBLE_TEXT_MAX = 20000;

    // -----------------------------------------------------------------------
    // Datos
    // -----------------------------------------------------------------------

    function parseBodyJson(value) {
        if (!value) {
            return {};
        }
        if (typeof value === 'object') {
            return value;
        }
        try {
            return JSON.parse(value) || {};
        } catch (e) {
            return {};
        }
    }

    function normalizeMessage(raw) {
        var bodyJson = parseBodyJson(raw.body_json);
        var role = raw.llm_role || null;
        if (!role) {
            role = raw.message_type === 'notification' || !raw.body ? 'skip' : 'note';
        }
        return {
            id: raw.id,
            role: role,
            body: raw.body || '',
            bodyJson: bodyJson,
            attachments: (raw.attachment_ids || []).map(function (att) {
                return { id: att.id, name: att.name || att.filename, mimetype: att.mimetype || '' };
            }),
        };
    }

    function textOf(html) {
        return String(html || '').replace(/<[^>]*>/g, '').trim();
    }

    function isToolCallOnly(msg) {
        return msg.role === 'assistant' &&
            (msg.bodyJson.tool_calls || []).length > 0 &&
            !textOf(msg.body);
    }

    function newTab(threadId, name) {
        return {
            key: 't' + threadId,
            threadId: threadId,
            name: name || 'Chat IA',
            messages: [],
            hasMore: false,
            loaded: false,
            loading: false,
            streaming: false,
            error: '',
            draft: '',
            attachments: [],
            uploading: 0,
            openGroups: {},
            unread: false,
        };
    }

    async function readSSE(response, onEvent) {
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';
        for (;;) {
            var chunk = await reader.read();
            if (chunk.done) {
                break;
            }
            buffer += decoder.decode(chunk.value, { stream: true });
            var blocks = buffer.split('\n\n');
            buffer = blocks.pop() || '';
            for (var i = 0; i < blocks.length; i++) {
                var line = blocks[i].trim();
                if (line.indexOf('data: ') !== 0) {
                    continue;
                }
                try {
                    onEvent(JSON.parse(line.slice(6)));
                } catch (e) {
                    console.warn('llm_thread: evento SSE inválido', e);
                }
            }
        }
    }

    function fileToBase64(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () {
                var result = String(reader.result || '');
                resolve(result.slice(result.indexOf(',') + 1));
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    function canInspectTools() {
        return session.llm_tool_debug !== false;
    }

    // -----------------------------------------------------------------------
    // Mensaje
    // -----------------------------------------------------------------------

    class LLMFloatingMessage extends Component {
        constructor() {
            super(...arguments);
            this.bodyRef = useRef('body');
            this._renderedBody = null;
            this._enhancedBody = null;
            var self = this;
            onMounted(function () { self._syncBody(); });
            onPatched(function () { self._syncBody(); });
        }

        get msg() {
            return this.props.msg;
        }

        get thinking() {
            return this.msg.bodyJson.thinking || '';
        }

        get thinkingActive() {
            return Boolean(this.msg.bodyJson.thinking_active);
        }

        get thinkingHtml() {
            return llmUi.thinkingToHtml(this.thinking);
        }

        get thinkingLabel() {
            if (this.thinkingActive) {
                return llmUi.thinkingHeadline(this.thinking) || 'Pensando…';
            }
            var ms = this.msg.bodyJson.thinking_ms;
            return ms ? 'Pensó durante ' + llmUi.formatDuration(ms) : 'Razonamiento';
        }

        get hasBody() {
            return Boolean(textOf(this.msg.body)) || this.msg.body.indexOf('<img') !== -1;
        }

        get metaLine() {
            return this.props.live ? '' : llmUi.responseMetaLine(this.msg.bodyJson);
        }

        _syncBody() {
            var el = this.bodyRef.el;
            if (!el) {
                return;
            }
            if (this._renderedBody !== this.msg.body) {
                el.innerHTML = this.msg.body;
                this._renderedBody = this.msg.body;
                this._enhancedBody = null;
            }
            if (!this.props.live && this._enhancedBody !== this.msg.body) {
                this._enhancedBody = this.msg.body;
                try {
                    var ctx = Object.create(Message.prototype);
                    ctx.env = this.env;
                    ctx._llmEnhanceAssistantDom(el.parentElement);
                } catch (e) {
                    console.warn('llm_thread: no se pudo mejorar el contenido', e);
                }
            }
        }

        async onCopy() {
            try {
                await navigator.clipboard.writeText((this.bodyRef.el && this.bodyRef.el.innerText) || textOf(this.msg.body));
                llmEnvUtils.llmNotify(this.env, { message: 'Copiado al portapapeles', type: 'success' });
            } catch (e) {
                llmEnvUtils.llmNotify(this.env, { message: 'No se pudo copiar', type: 'danger' });
            }
        }
    }
    LLMFloatingMessage.template = 'llm_thread.LLMFloatingMessage';
    LLMFloatingMessage.props = {
        msg: Object,
        live: { type: Boolean, optional: true },
    };

    // -----------------------------------------------------------------------
    // Conversación (una pestaña)
    // -----------------------------------------------------------------------

    class LLMFloatingConversation extends Component {
        constructor() {
            super(...arguments);
            this.scrollRef = useRef('scroll');
            this.inputRef = useRef('input');
            this.fileRef = useRef('file');
            this.stickToBottom = true;
            this._lastTabKey = null;
            var self = this;
            onMounted(function () { self._afterRender(true); });
            onPatched(function () { self._afterRender(false); });
        }

        get tab() {
            return this.props.tab;
        }

        get meterComponent() {
            return llmUi.extraComponents.LLMContextMeter || null;
        }

        get canInspectTools() {
            return canInspectTools();
        }

        get canSend() {
            var tab = this.tab;
            return !tab.streaming && !tab.uploading &&
                Boolean(tab.draft.trim() || tab.attachments.length);
        }

        get waiting() {
            var msgs = this.tab.messages.filter(function (m) {
                return m.role !== 'skip' && m.role !== 'note';
            });
            return this.tab.streaming && (!msgs.length || msgs[msgs.length - 1].role === 'user');
        }

        get items() {
            var tab = this.tab;
            var items = [];
            var group = null;
            for (var i = 0; i < tab.messages.length; i++) {
                var msg = tab.messages[i];
                if (msg.role === 'skip') {
                    continue;
                }
                if (msg.role === 'tool' || isToolCallOnly(msg)) {
                    if (!group) {
                        group = { type: 'steps', key: 'g' + msg.id, steps: [], modelMs: 0 };
                        items.push(group);
                    }
                    if (msg.role === 'assistant') {
                        group.modelMs += msg.bodyJson.duration_ms || 0;
                        if (msg.bodyJson.thinking) {
                            group.steps.push({ key: 's' + msg.id, kind: 'thinking', msg: msg });
                        }
                    } else {
                        group.steps.push(Object.assign({ key: 's' + msg.id, kind: 'tool' }, this._toolStep(msg)));
                    }
                    continue;
                }
                group = null;
                items.push({ type: 'message', key: 'm' + msg.id, msg: msg });
            }
            var last = items[items.length - 1];
            for (var j = 0; j < items.length; j++) {
                if (items[j].type === 'steps') {
                    this._decorateGroup(items[j], tab.streaming && items[j] === last);
                }
            }
            return items;
        }

        _toolStep(msg) {
            var data = msg.bodyJson;
            var call = data.tool_call || {};
            var rawArgs = data.arguments || (call.function && call.function.arguments);
            var step = llmUi.describeToolStep(data.tool_name, rawArgs, data.status, data.result);
            var result = '';
            if ('result' in data) {
                result = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
            }
            return Object.assign(step, {
                running: data.status === 'requested' || data.status === 'executing',
                error: data.status === 'error' ? String(data.error || '') : '',
                durationMs: data.duration_ms || 0,
                duration: data.duration_ms ? llmUi.formatDuration(data.duration_ms) : '',
                args: JSON.stringify(llmUi.parseToolArgs(rawArgs), null, 2),
                result: result.length > 20000 ? result.slice(0, 20000) + '\n…' : result,
            });
        }

        _decorateGroup(group, running) {
            var tools = group.steps.filter(function (s) { return s.kind === 'tool'; });
            var ms = group.modelMs;
            tools.forEach(function (s) { ms += s.durationMs; });
            group.running = running;
            group.open = running || Boolean(this.tab.openGroups[group.key]);
            group.errors = tools.filter(function (s) { return s.error; }).length;
            if (running) {
                var current = group.steps[group.steps.length - 1];
                group.label = current && current.kind === 'tool'
                    ? [current.label, current.target].filter(Boolean).join(' ')
                    : 'Pensando…';
                group.detail = '';
            } else {
                var parts = [];
                if (tools.length) {
                    parts.push(tools.length === 1 ? '1 herramienta' : tools.length + ' herramientas');
                }
                if (group.errors) {
                    parts.push(group.errors === 1 ? '1 error' : group.errors + ' errores');
                }
                group.label = ms ? 'Trabajó ' + llmUi.formatDuration(ms) : 'Trabajó';
                group.detail = parts.join(' · ');
            }
        }

        isLiveMessage(item) {
            var msgs = this.tab.messages;
            return Boolean(this.tab.streaming && msgs.length && msgs[msgs.length - 1].id === item.msg.id);
        }

        thinkingStepLabel(step) {
            var data = step.msg.bodyJson;
            if (data.thinking_active) {
                return llmUi.thinkingHeadline(data.thinking) || 'Pensando…';
            }
            return data.thinking_ms ? 'Pensó durante ' + llmUi.formatDuration(data.thinking_ms) : 'Razonamiento';
        }

        thinkingStepHtml(step) {
            return llmUi.thinkingToHtml(step.msg.bodyJson.thinking);
        }

        toggleGroup(group) {
            if (group.running) {
                return;
            }
            this.tab.openGroups[group.key] = !this.tab.openGroups[group.key];
        }

        onScroll() {
            var el = this.scrollRef.el;
            if (el) {
                this.stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }
        }

        _afterRender(mounted) {
            var el = this.scrollRef.el;
            if (!el) {
                return;
            }
            if (mounted || this._lastTabKey !== this.tab.key) {
                this._lastTabKey = this.tab.key;
                this.stickToBottom = true;
                if (this.inputRef.el) {
                    // OWL 1 no enlaza la propiedad value del textarea.
                    this.inputRef.el.value = this.tab.draft;
                    this.inputRef.el.focus();
                }
            }
            if (this.stickToBottom) {
                el.scrollTop = el.scrollHeight;
            }
        }

        onInput(ev) {
            this.tab.draft = ev.target.value;
            this._autosize(ev.target);
        }

        _autosize(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 160) + 'px';
        }

        onKeydown(ev) {
            if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
                ev.preventDefault();
                this.send();
            }
        }

        async send() {
            if (!this.canSend) {
                return;
            }
            this.stickToBottom = true;
            await this.props.dock.send(this.tab);
            if (this.inputRef.el) {
                this.inputRef.el.value = this.tab.draft;
                this._autosize(this.inputRef.el);
            }
        }

        stop() {
            this.props.dock.stop(this.tab);
        }

        onClickAttach() {
            if (this.fileRef.el) {
                this.fileRef.el.click();
            }
        }

        async onFilesSelected(ev) {
            var files = Array.prototype.slice.call(ev.target.files || []);
            ev.target.value = '';
            await this.props.dock.uploadFiles(this.tab, files);
        }

        removeAttachment(att) {
            this.tab.attachments = this.tab.attachments.filter(function (a) { return a.id !== att.id; });
        }

        async onPaste(ev) {
            var files = Array.prototype.slice.call((ev.clipboardData && ev.clipboardData.files) || []);
            if (files.length) {
                ev.preventDefault();
                await this.props.dock.uploadFiles(this.tab, files);
            }
        }

        loadOlder() {
            this.stickToBottom = false;
            this.props.dock.loadMessages(this.tab, true);
        }
    }
    LLMFloatingConversation.template = 'llm_thread.LLMFloatingConversation';
    LLMFloatingConversation.components = { LLMFloatingMessage: LLMFloatingMessage };
    LLMFloatingConversation.props = {
        tab: Object,
        dock: Object,
    };

    // -----------------------------------------------------------------------
    // Dock (ventana con pestañas)
    // -----------------------------------------------------------------------

    class LLMFloatingDock extends Component {
        constructor() {
            super(...arguments);
            this.storageKey = 'llm_floating_dock_v2_' + (this.env.session ? this.env.session.uid : session.uid);
            this.aborts = {};
            this.state = useState({
                tabs: [],
                activeKey: null,
                open: false,
                minimized: false,
                expanded: false,
            });
            this._restore();
            var self = this;
            this._onThreadUpdated = function (ev) { self._applyThreadUpdate(ev.detail); };
            this._onNote = function (ev) { self._applyNote(ev.detail); };
            window.addEventListener('llm-thread-updated', this._onThreadUpdated);
            window.addEventListener('llm-thread-note', this._onNote);
            var bus = this.env.services && this.env.services.bus_service;
            if (bus && bus.on) {
                bus.on('notification', this, this._onBusNotification);
            }
            if (this.props.registerDock) {
                this.props.registerDock(this);
            }
            onWillUnmount(function () {
                window.removeEventListener('llm-thread-updated', self._onThreadUpdated);
                window.removeEventListener('llm-thread-note', self._onNote);
                if (bus && bus.off) {
                    bus.off('notification', self, self._onBusNotification);
                }
                Object.keys(self.aborts).forEach(function (key) {
                    self.aborts[key].abort();
                });
            });
        }

        /** Referencia al dock para los hijos (OWL 1 no acepta ``this`` en plantillas). */
        get dockRef() {
            return this;
        }

        get activeTab() {
            var key = this.state.activeKey;
            return this.state.tabs.find(function (t) { return t.key === key; }) || null;
        }

        get expandIcon() {
            return this.state.expanded ? 'fa-compress' : 'fa-expand';
        }

        get minimizeIcon() {
            return this.state.minimized ? 'fa-window-maximize' : 'fa-minus';
        }

        _persist() {
            try {
                localStorage.setItem(this.storageKey, JSON.stringify({
                    tabs: this.state.tabs.map(function (t) { return { threadId: t.threadId, name: t.name }; }),
                    activeKey: this.state.activeKey,
                    open: this.state.open,
                    minimized: this.state.minimized,
                    expanded: this.state.expanded,
                }));
            } catch (e) {
                // Navegación privada o almacenamiento bloqueado: sin persistencia.
            }
        }

        _restore() {
            var saved = null;
            try {
                saved = JSON.parse(localStorage.getItem(this.storageKey) || 'null');
            } catch (e) {
                saved = null;
            }
            if (!saved || !Array.isArray(saved.tabs) || !saved.tabs.length) {
                return;
            }
            this.state.tabs = saved.tabs.map(function (t) { return newTab(t.threadId, t.name); });
            this.state.activeKey = saved.activeKey || this.state.tabs[0].key;
            this.state.open = Boolean(saved.open);
            this.state.minimized = Boolean(saved.minimized);
            this.state.expanded = Boolean(saved.expanded);
            if (this.state.open && !this.state.minimized && this.activeTab) {
                this.loadMessages(this.activeTab);
            }
        }

        async openThread(threadId, name) {
            var tab = this.state.tabs.find(function (t) { return t.threadId === threadId; });
            if (!tab) {
                this.state.tabs.push(newTab(threadId, name));
                tab = this.state.tabs[this.state.tabs.length - 1];
            } else if (name) {
                tab.name = name;
            }
            this.state.open = true;
            this.state.minimized = false;
            this.activate(tab);
        }

        activate(tab) {
            this.state.activeKey = tab.key;
            tab.unread = false;
            if (!tab.loaded && !tab.loading) {
                this.loadMessages(tab);
            }
            this._persist();
        }

        closeTab(tab) {
            if (tab.streaming) {
                this.stop(tab);
            }
            var index = this.state.tabs.findIndex(function (t) { return t.key === tab.key; });
            this.state.tabs.splice(index, 1);
            if (this.state.activeKey === tab.key) {
                var next = this.state.tabs[Math.max(0, index - 1)];
                this.state.activeKey = next ? next.key : null;
                if (next && !next.loaded) {
                    this.loadMessages(next);
                }
            }
            if (!this.state.tabs.length) {
                this.state.open = false;
            }
            this._persist();
        }

        async newChat() {
            try {
                var created = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'create',
                    args: [{}],
                });
                var threadId = Array.isArray(created) ? created[0] : created;
                var rows = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'read',
                    args: [[threadId], ['name']],
                });
                await this.openThread(threadId, rows && rows[0] && rows[0].name);
                if (this.props.onThreadsChanged) {
                    this.props.onThreadsChanged();
                }
            } catch (e) {
                console.error('LLMFloatingDock.newChat', e);
                llmEnvUtils.llmNotify(this.env, { message: 'No se pudo crear el chat.', type: 'danger' });
            }
        }

        toggleMinimize() {
            this.state.minimized = !this.state.minimized;
            if (!this.state.minimized && this.activeTab && !this.activeTab.loaded) {
                this.loadMessages(this.activeTab);
            }
            this._persist();
        }

        toggleExpand() {
            this.state.expanded = !this.state.expanded;
            this._persist();
        }

        closeAll() {
            var self = this;
            this.state.tabs.slice().forEach(function (tab) {
                if (tab.streaming) {
                    self.stop(tab);
                }
            });
            this.state.open = false;
            this._persist();
        }

        openInFullChat() {
            var tab = this.activeTab;
            if (!tab) {
                return;
            }
            this.env.bus.trigger('do-action', {
                action: 'llm_thread.action_llm_chat',
                options: { additional_context: { active_id: 'llm.thread_' + tab.threadId } },
            });
        }

        async loadMessages(tab, older) {
            if (tab.loading) {
                return;
            }
            tab.loading = true;
            try {
                var beforeId = older && tab.messages.length ? tab.messages[0].id : false;
                var res = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'llm_ui_load_messages',
                    args: [tab.threadId, PAGE_SIZE, beforeId],
                });
                var incoming = (res.messages || []).map(normalizeMessage);
                tab.messages = older ? incoming.concat(tab.messages) : incoming;
                tab.hasMore = Boolean(res.has_more);
                if (res.thread && res.thread.name) {
                    tab.name = res.thread.name;
                }
                tab.loaded = true;
            } catch (e) {
                tab.error = (e && e.message && e.message.data && e.message.data.message) || 'No se pudo cargar la conversación.';
            } finally {
                tab.loading = false;
            }
        }

        _upsert(tab, raw) {
            var msg = normalizeMessage(raw);
            var index = tab.messages.findIndex(function (m) { return m.id === msg.id; });
            if (index >= 0) {
                tab.messages[index] = msg;
            } else {
                tab.messages.push(msg);
            }
        }

        /** Qué está viendo el usuario detrás del popup (para la tool odoo_active_screen). */
        collectScreenContext() {
            try {
                if (document.querySelector('.o_action_manager .o_LLMChatClientAction')) {
                    return { is_llm_chat: true };
                }
                var hash = new URLSearchParams((window.location.hash || '').replace(/^#/, ''));
                var root = document.querySelector('.o_action_manager');
                var visible = ((root && root.innerText) || '')
                    .replace(/[ \t]+\n/g, '\n')
                    .replace(/\n{3,}/g, '\n\n')
                    .trim()
                    .slice(0, VISIBLE_TEXT_MAX);
                var breadcrumbs = Array.prototype.slice.call(
                    document.querySelectorAll('.o_control_panel .breadcrumb-item')
                ).map(function (el) { return el.innerText.trim(); }).filter(Boolean).join(' / ');
                return {
                    model: hash.get('model') || false,
                    res_id: Number(hash.get('id')) || false,
                    view_type: hash.get('view_type') || false,
                    action_name: breadcrumbs.split(' / ')[0] || false,
                    action_id: Number(hash.get('action')) || false,
                    title: document.title,
                    breadcrumbs: breadcrumbs,
                    url: window.location.href,
                    visible_text: visible,
                };
            } catch (e) {
                console.warn('llm_thread: no se pudo leer la pantalla activa', e);
                return null;
            }
        }

        async send(tab) {
            var text = tab.draft.trim();
            var attachmentIds = tab.attachments.map(function (a) { return a.id; });
            if ((!text && !attachmentIds.length) || tab.streaming) {
                return;
            }
            tab.draft = '';
            tab.attachments = [];
            tab.error = '';
            tab.streaming = true;
            var controller = new AbortController();
            this.aborts[tab.key] = controller;
            var self = this;
            try {
                var csrf = core.csrf_token || (typeof odoo !== 'undefined' && odoo.csrf_token) || '';
                // Odoo 14 trata application/json como JsonRequest: form-urlencoded.
                var form = new URLSearchParams();
                form.append('csrf_token', csrf);
                form.append('message', text);
                form.append('attachment_ids', JSON.stringify(attachmentIds));
                form.append('screen_context', JSON.stringify(this.collectScreenContext() || {}));
                var response = await fetch(
                    '/llm/thread/generate?thread_id=' + tab.threadId + '&csrf_token=' + encodeURIComponent(csrf),
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
                        credentials: 'include',
                        signal: controller.signal,
                        body: form.toString(),
                    }
                );
                var ctype = (response.headers.get('Content-Type') || '').toLowerCase();
                if (!response.ok || ctype.indexOf('text/event-stream') === -1) {
                    var detail = (await response.text()).replace(/<[^>]*>/g, ' ').slice(0, 300);
                    throw new Error(detail || response.statusText);
                }
                await readSSE(response, function (data) { self._onStreamEvent(tab, data); });
            } catch (e) {
                if (!e || e.name !== 'AbortError') {
                    tab.error = (e && e.message) || 'Error al enviar el mensaje.';
                    if (!tab.draft) {
                        tab.draft = text;
                    }
                }
            } finally {
                tab.streaming = false;
                delete this.aborts[tab.key];
                if (tab.key !== this.state.activeKey) {
                    tab.unread = true;
                }
                window.dispatchEvent(new CustomEvent('llm-experience-refresh-meter'));
                if (this.props.onThreadsChanged) {
                    this.props.onThreadsChanged();
                }
            }
        }

        _onStreamEvent(tab, data) {
            switch (data.type) {
                case 'message_create':
                case 'message_chunk':
                case 'message_update':
                    this._upsert(tab, data.message);
                    break;
                case 'thread_update':
                    this._applyThreadUpdate(data.thread);
                    window.dispatchEvent(new CustomEvent('llm-thread-updated', { detail: data.thread }));
                    break;
                case 'tool_end':
                    window.dispatchEvent(new CustomEvent('llm-experience-refresh-meter'));
                    break;
                case 'error':
                    tab.error = data.error;
                    break;
            }
        }

        stop(tab) {
            if (this.aborts[tab.key]) {
                this.aborts[tab.key].abort();
            }
        }

        async uploadFiles(tab, files) {
            for (var i = 0; i < files.length; i++) {
                var file = files[i];
                tab.uploading++;
                try {
                    var datas = await fileToBase64(file);
                    var attId = await this.env.services.rpc({
                        model: 'ir.attachment',
                        method: 'create',
                        args: [{
                            name: file.name,
                            datas: datas,
                            mimetype: file.type || false,
                            res_model: 'mail.compose.message',
                            res_id: 0,
                        }],
                    });
                    tab.attachments.push({ id: attId, name: file.name, mimetype: file.type });
                } catch (e) {
                    llmEnvUtils.llmNotify(this.env, {
                        message: 'No se pudo adjuntar ' + file.name,
                        type: 'danger',
                    });
                } finally {
                    tab.uploading--;
                }
            }
        }

        _applyThreadUpdate(thread) {
            if (!thread || !thread.id) {
                return;
            }
            var changed = false;
            this.state.tabs.forEach(function (tab) {
                if (tab.threadId === thread.id && thread.name && tab.name !== thread.name) {
                    tab.name = thread.name;
                    changed = true;
                }
            });
            if (changed) {
                this._persist();
            }
            if (this.props.onThreadRenamed) {
                this.props.onThreadRenamed(thread);
            }
        }

        _applyNote(detail) {
            var tab = detail && this.state.tabs.find(function (t) { return t.threadId === detail.threadId; });
            if (tab && detail.message) {
                this._upsert(tab, detail.message);
            }
        }

        _onBusNotification(notifications) {
            var self = this;
            (notifications || []).forEach(function (notif) {
                var message = Array.isArray(notif) ? notif[1] : notif;
                if (!message || typeof message !== 'object') {
                    return;
                }
                if (message.type === 'llm.thread/update') {
                    self._applyThreadUpdate(message);
                } else if (message.type === 'llm.thread/delete') {
                    (message.ids || []).forEach(function (id) {
                        var tab = self.state.tabs.find(function (t) { return t.threadId === id; });
                        if (tab) {
                            self.closeTab(tab);
                        }
                    });
                }
            });
        }
    }
    LLMFloatingDock.template = 'llm_thread.LLMFloatingDock';
    LLMFloatingDock.components = { LLMFloatingConversation: LLMFloatingConversation };
    LLMFloatingDock.props = {
        registerDock: { type: Function, optional: true },
        onThreadsChanged: { type: Function, optional: true },
        onThreadRenamed: { type: Function, optional: true },
    };

    return {
        LLMFloatingDock: LLMFloatingDock,
        LLMFloatingConversation: LLMFloatingConversation,
        LLMFloatingMessage: LLMFloatingMessage,
        normalizeMessage: normalizeMessage,
    };
});
