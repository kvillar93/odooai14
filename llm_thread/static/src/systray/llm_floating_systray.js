odoo.define('llm_thread/static/src/systray/llm_floating_systray.js', function (require) {
    'use strict';

    const SystrayMenu = require('web.SystrayMenu');
    const Widget = require('web.Widget');
    const session = require('web.session');
    const { Component } = owl;
    const { useState } = owl.hooks;

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');
    const { LLMFloatingDock } = require('llm_thread/static/src/systray/llm_floating_dock.js');


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
            var self = this;
            this.state = useState({
                search: '',
                browseThreads: [],
                browseOffset: 0,
                hasMoreBrowse: false,
                searchMode: false,
                searchResults: [],
                loadingThreads: false,
                loadingMore: false,
                searchingRemote: false,
            });
            this.dock = null;
            this.registerDock = function (dock) {
                self.dock = dock;
            };
            this.onThreadsChanged = function () {
                self.state.browseOffset = 0;
            };
            this.onThreadRenamed = function (thread) {
                [self.state.browseThreads, self.state.searchResults].forEach(function (list) {
                    list.forEach(function (row) {
                        if (row.id === thread.id && thread.name) {
                            row.name = thread.name;
                        }
                    });
                });
            };

            this._debouncedSearch = _.debounce(function () {
                self._runSearchRemote();
            }, 400);
        }

        get messaging() {
            return this.env.messaging;
        }

        /** Referencia para el menú (la plantilla pasa ``systray`` como prop). */
        get systray() {
            return this;
        }

        get displayedThreads() {
            if (this.state.searchMode && (this.state.search || '').trim()) {
                return this.state.searchResults;
            }
            return this.state.browseThreads;
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
            if (this.dock) {
                await this.dock.newChat();
            }
        }

        /** Abre el hilo como pestaña del chat flotante (convive con el chat completo). */
        async openThread(threadId) {
            var row = this.displayedThreads.find(function (t) { return t.id === threadId; });
            if (this.dock) {
                await this.dock.openThread(threadId, row && row.name);
            }
        }
    }

    Object.assign(LLMFloatingSystray, {
        components: {
            LLMFloatingDock: LLMFloatingDock,
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
