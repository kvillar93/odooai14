odoo.define('llm_thread/static/src/systray/llm_floating_systray.js', function (require) {
    'use strict';

    const SystrayMenu = require('web.SystrayMenu');
    const Widget = require('web.Widget');
    const session = require('web.session');
    const { Component } = owl;
    const { useState } = owl.hooks;

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');
    const LLMChat = require('llm_thread/static/src/components/llm_chat/llm_chat.js');

    const LLM_ACTIVE_VIEW_HTML_MAX_CHARS = 2500000;
    const LLM_SYSTRAY_ACTION_ID = 'llm_systray_float';

    class LLMFloatingSystrayMenuBody extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            this._onSearchInput = this._onSearchInput.bind(this);
        }

        get systray() {
            return this.props.systray;
        }

        _onSearchInput(ev) {
            this.props.systray.onSearchInput(ev);
        }

        async onClickThreadRow(ev) {
            const id = Number(ev.currentTarget.dataset.threadId);
            if (!id) return;
            const systray = this.props.systray;
            await systray.openThread(id);
            var $li = $(this.el).closest('.o_llm_floating_systray_item');
            if ($li.length) {
                $li.find('[data-toggle="dropdown"]').dropdown('hide');
            }
        }

        async onClickNewChat() {
            const systray = this.props.systray;
            await systray.onClickNewChat();
            var $li = $(this.el).closest('.o_llm_floating_systray_item');
            if ($li.length) {
                $li.find('[data-toggle="dropdown"]').dropdown('hide');
            }
        }

        onClickLoadMore() {
            this.props.systray.loadMoreBrowse();
        }
    }

    Object.assign(LLMFloatingSystrayMenuBody, {
        props: { systray: Object },
        template: 'llm_thread.LLMFloatingSystrayMenuBody',
    });

    class LLMFloatingSystray extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                var messaging = this.env.messaging;
                var llmChat = messaging && messaging.llmChat;
                var activeThread = llmChat && llmChat.activeThread;
                return {
                    messaging: messaging ? messaging.__state : undefined,
                    isInitialized: messaging && messaging.isInitialized,
                    // Trackear el nombre del hilo activo para que el título del
                    // panel flotante se actualice cuando cambia (SSE o renombrado)
                    activeThreadName: activeThread ? activeThread.name : undefined,
                };
            }.bind(this));

            var self = this;
            this.state = useState({
                search: '',
                browseThreads: [],
                browseOffset: 0,
                hasMoreBrowse: false,
                searchMode: false,
                searchResults: [],
                panelOpen: false,
                panelMinimized: false,
                loadingThreads: false,
                loadingMore: false,
                searchingRemote: false,
                initializing: false,
            });

            this._debouncedSearch = _.debounce(function () {
                self._runSearchRemote();
            }, 400);
        }

        get messaging() {
            return this.env.messaging;
        }

        get displayedThreads() {
            if (this.state.searchMode && (this.state.search || '').trim()) {
                return this.state.searchResults;
            }
            return this.state.browseThreads;
        }

        get canShowFloatingPanel() {
            return this.state.panelOpen && !this._isFullLlmChatAction();
        }

        _isFullLlmChatAction() {
            return Boolean(document.querySelector('.o_LLMChatClientAction'));
        }

        get floatingPanelTitle() {
            var t = this.messaging.llmChat && this.messaging.llmChat.activeThread;
            var raw = t && t.name;
            if (raw !== undefined && raw !== null && String(raw).trim() !== '') {
                return String(raw).trim();
            }
            return this.env._t('Chat IA');
        }

        async _onDropdownShow() {
            this.state.search = '';
            this.state.searchMode = false;
            this.state.searchResults = [];
            await this.loadBrowseFirstPage();
        }

        async loadBrowseFirstPage() {
            this.state.loadingThreads = true;
            try {
                var uid = session.uid;
                var threads = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'search_read',
                    args: [[['user_id', '=', uid]], ['name', 'write_date']],
                    orderBy: [{name: 'write_date', asc: false}],
                    kwargs: { limit: 30, offset: 0 },
                });
                this.state.browseThreads = threads;
                this.state.browseOffset = threads.length;
                this.state.hasMoreBrowse = threads.length === 30;
            } catch (e) {
                console.error('LLMFloatingSystray.loadBrowseFirstPage', e);
            } finally {
                this.state.loadingThreads = false;
            }
        }

        async loadMoreBrowse() {
            if (!this.state.hasMoreBrowse || this.state.loadingMore || this.state.searchMode) return;
            this.state.loadingMore = true;
            try {
                var uid = session.uid;
                var threads = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'search_read',
                    args: [[['user_id', '=', uid]], ['name', 'write_date']],
                    orderBy: [{name: 'write_date', asc: false}],
                    kwargs: { limit: 30, offset: this.state.browseOffset },
                });
                this.state.browseThreads = this.state.browseThreads.concat(threads);
                this.state.browseOffset += threads.length;
                this.state.hasMoreBrowse = threads.length === 30;
            } catch (e) {
                console.error('LLMFloatingSystray.loadMoreBrowse', e);
            } finally {
                this.state.loadingMore = false;
            }
        }

        onSearchInput(ev) {
            var v = ev.target.value || '';
            this.state.search = v;
            var q = v.trim();
            if (!q) {
                this.state.searchMode = false;
                this.state.searchResults = [];
                this.state.searchingRemote = false;
                this._debouncedSearch.cancel();
                return;
            }
            this.state.searchMode = true;
            this.state.searchingRemote = true;
            this._debouncedSearch();
        }

        async _runSearchRemote() {
            var q = (this.state.search || '').trim();
            if (!q) {
                this.state.searchMode = false;
                this.state.searchResults = [];
                return;
            }
            this.state.searchingRemote = true;
            try {
                var uid = session.uid;
                var threads = await this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'search_read',
                    args: [[['user_id', '=', uid], ['name', 'ilike', '%' + q + '%']], ['name', 'write_date']],
                    orderBy: [{name: 'write_date', asc: false}],
                    kwargs: { limit: 500 },
                });
                this.state.searchResults = threads;
            } catch (e) {
                console.error('LLMFloatingSystray._runSearchRemote', e);
            } finally {
                this.state.searchingRemote = false;
            }
        }

        async onClickNewChat() {
            this.state.initializing = true;
            try {
                var llmChat = this.messaging.llmChat;
                llmChat.update({ isSystrayFloatingMode: true });
                await this.env.messagingCreatedPromise;
                await llmChat.ensureDataLoaded();
                var thread = await llmChat.createThread({});
                if (thread) {
                    await this.loadBrowseFirstPage();
                    await this.openThread(thread.id);
                }
            } catch (e) {
                console.error('LLMFloatingSystray.onClickNewChat', e);
            } finally {
                this.state.initializing = false;
            }
        }

        async openThread(threadId) {
            this.state.panelOpen = true;
            this.state.panelMinimized = false;
            var llmChat = this.messaging.llmChat;
            llmChat.update({ isSystrayFloatingMode: true });
            await this.env.messagingCreatedPromise;

            var systrayScopeKey = LLM_SYSTRAY_ACTION_ID + '|';
            var alreadySystray = llmChat.chatInitScopeKey === systrayScopeKey && llmChat.llmChatView;

            if (!alreadySystray) {
                this.state.initializing = true;
                try {
                    var action = {
                        id: LLM_SYSTRAY_ACTION_ID,
                        name: this.env._t('Chat IA flotante'),
                        context: {},
                    };
                    await llmChat.initializeLLMChat(action, 'llm.thread_' + threadId, []);
                } catch (e) {
                    console.error('LLMFloatingSystray.openThread', e);
                    this.state.initializing = false;
                    return;
                } finally {
                    this.state.initializing = false;
                }
            }

            try {
                await llmChat.selectThread(threadId);
            } catch (e) {
                console.error('LLMFloatingSystray.selectThread', e);
            }
            var self = this;
            [100, 400, 1000].forEach(function (ms) {
                window.setTimeout(function () {
                    if (self.env && self.env.messagingBus) {
                        self.env.messagingBus.trigger('llm-stream-update');
                    }
                }, ms);
            });
        }

        onClickFullChat() {
            var active = this.messaging.llmChat && this.messaging.llmChat.activeThread;
            if (!active) return;
            this.state.panelOpen = false;
            this.state.panelMinimized = false;
            this.messaging.llmChat.update({ isSystrayFloatingMode: false });
            this.env.bus.trigger('do-action', {
                action: 'llm_thread.action_llm_chat',
                options: {
                    active_id: this.messaging.llmChat.threadToActiveId(active),
                    clear_breadcrumbs: false,
                },
            });
        }

        onClosePanel() {
            this.state.panelOpen = false;
            this.state.panelMinimized = false;
            if (this.messaging.llmChat) {
                this.messaging.llmChat.update({ isSystrayFloatingMode: false });
            }
        }

        onClickMinimizePanel() {
            this.state.panelMinimized = true;
        }

        onClickRestorePanel() {
            this.state.panelMinimized = false;
            var self = this;
            [100, 400].forEach(function (ms) {
                window.setTimeout(function () {
                    if (self.env && self.env.messagingBus) {
                        self.env.messagingBus.trigger('llm-stream-update');
                    }
                }, ms);
            });
        }

        onClickFloatingHeaderBar() {
            if (this.state.panelMinimized) {
                this.onClickRestorePanel();
            }
        }

        noop() {}

        _escapeHtmlForSnapshot(s) {
            return String(s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        _sanitizeFilenameFromPageTitle() {
            var s = (document.title || '').trim();
            s = s.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '');
            s = s.replace(/\s+/g, '-');
            s = s.replace(/-+/g, '-').replace(/^-|-$/g, '');
            if (s.length > 100) s = s.slice(0, 100).replace(/-+$/g, '');
            if (!s) return 'documento-' + Date.now();
            return s;
        }

        _buildActiveViewHtmlDocument() {
            var root = document.querySelector('.o_action_manager') || document.body;
            var clone = root.cloneNode(true);
            clone.querySelectorAll('script, iframe, object, embed').forEach(function (n) { n.remove(); });
            var metaLines = [
                this.env._t('URL') + ': ' + window.location.href,
                this.env._t('Título') + ': ' + document.title,
            ];
            var metaComment = '<!--\n' + metaLines.join('\n') + '\n-->';
            var title = this._escapeHtmlForSnapshot(document.title);
            return '<!DOCTYPE html>\n<html lang="es">\n<head>\n<meta charset="utf-8"/>\n<title>' + title + '</title>\n</head>\n<body>\n' + metaComment + '\n' + clone.outerHTML + '\n</body>\n</html>';
        }

        async onClickAttachActiveViewHtml() {
            try {
                var panel = document.querySelector('.o_llm_floating_panel');
                var input = panel && panel.querySelector('.o_FileUploader_input');
                if (!input) {
                    this.env.services.notification.notify({
                        message: this.env._t('Abre una conversación antes de adjuntar el HTML.'),
                        type: 'warning',
                    });
                    return;
                }
                var html = this._buildActiveViewHtmlDocument();
                var truncated = false;
                if (html.length > LLM_ACTIVE_VIEW_HTML_MAX_CHARS) {
                    html = html.slice(0, LLM_ACTIVE_VIEW_HTML_MAX_CHARS) + '\n<!-- truncado -->\n';
                    truncated = true;
                }
                var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
                var fileName = this._sanitizeFilenameFromPageTitle() + '.html';
                var file = new File([blob], fileName, { type: 'text/html' });
                var dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                input.dispatchEvent(new Event('change', { bubbles: true }));
                if (truncated) {
                    this.env.services.notification.notify({
                        message: this.env._t('El HTML se ha truncado por tamaño.'),
                        type: 'warning',
                    });
                }
            } catch (e) {
                console.error('[LLM attach HTML] ERROR:', e);
                this.env.services.notification.notify({
                    message: this.env._t('Error al adjuntar el HTML de la vista.'),
                    type: 'danger',
                });
            }
        }

        get systray() {
            return this;
        }
    }

    Object.assign(LLMFloatingSystray, {
        components: {
            LLMChat: LLMChat,
            LLMFloatingSystrayMenuBody: LLMFloatingSystrayMenuBody,
        },
        template: 'llm_thread.LLMFloatingSystray',
    });

    /**
     * Widget systray - sigue el patrón de web_progress:
     * - template renderiza el <li> con el icono siempre visible
     * - start() retorna inmediatamente (no bloquea)
     * - OWL se monta de forma diferida dentro del <li>
     */
    const LLMFloatingSystrayWidget = Widget.extend({
        name: 'llm_floating_systray',
        template: 'llm_thread.LLMFloatingSystrayWidget',

        start: function () {
            var self = this;
            var sup = this._super.apply(this, arguments);

            return session.user_has_group('llm_thread.group_llm_floating_chat').then(function (hasGroup) {
                if (!hasGroup) {
                    self.$el.addClass('d-none');
                    return sup;
                }

                self.$el.on('show.bs.dropdown', function () {
                    if (self._owl) {
                        self._owl._onDropdownShow();
                    }
                });

                self._mountOwlDeferred();
                return sup;
            });
        },

        _mountOwlDeferred: function () {
            var self = this;
            setTimeout(function () {
                self._doMountOwl();
            }, 0);
        },

        _doMountOwl: async function () {
            try {
                await owl.utils.whenReady();
                if (Component.env && Component.env.messagingCreatedPromise) {
                    await Component.env.messagingCreatedPromise;
                }
                if (this.isDestroyed()) return;
                this._owl = new LLMFloatingSystray(null, {});
                await this._owl.mount(this.el);
            } catch (e) {
                console.error('LLMFloatingSystray: error al montar componente OWL:', e);
            }
        },

        destroy: function () {
            if (this._owl) {
                try { this._owl.destroy(); } catch (_) {}
                this._owl = undefined;
            }
            this._super.apply(this, arguments);
        },
    });

    SystrayMenu.Items.push(LLMFloatingSystrayWidget);

    return LLMFloatingSystrayWidget;
});
