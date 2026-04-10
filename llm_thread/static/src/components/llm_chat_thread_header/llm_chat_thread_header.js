odoo.define('llm_thread/static/src/components/llm_chat_thread_header/llm_chat_thread_header.js', function (require) {
    'use strict';

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');
    const useStore = require('mail/static/src/component_hooks/use_store/use_store.js');
    const LLMChatThreadRelatedRecord = require('llm_thread/static/src/components/llm_chat_thread_related_record/llm_chat_thread_related_record.js');

    const { Component } = owl;
    const { useState, useRef, onMounted, onWillUnmount, onPatched } = owl.hooks;

    class LLMChatThreadHeader extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            useStore(function () {
                const record = this.props.record;
                return {
                    headerView: record && record.__state,
                };
            }.bind(this));

            this._threadNameInputRef = useRef('threadNameInput');
            this.state = useState({
                modelSearchQuery: '',
                shouldShowDropdown: false,
                shouldFocusSearch: false,
            });
            this.modelDropdownRef = useRef('modelDropdown');
            this.modelSearchInputRef = useRef('modelSearchInput');

            this.onToolSelectChange = this.onToolSelectChange.bind(this);
            this._onModelDropdownShown = this._onModelDropdownShown.bind(this);
            this._onModelDropdownHidden = this._onModelDropdownHidden.bind(this);
            this.onSelectModel = this.onSelectModel.bind(this);
            this.onSelectProvider = this.onSelectProvider.bind(this);
            this._preventDropdownClose = this._preventDropdownClose.bind(this);
            this.onModelSearchInput = this.onModelSearchInput.bind(this);

            const self = this;
            onMounted(function () {
                if (self.modelDropdownRef.el) {
                    self.modelDropdownRef.el.addEventListener('shown.bs.dropdown', self._onModelDropdownShown);
                    self.modelDropdownRef.el.addEventListener('hidden.bs.dropdown', self._onModelDropdownHidden);
                }
                if (self.llmChatThreadHeaderView) {
                    self.llmChatThreadHeaderView.update({
                        llmChatThreadNameInputRef: self._threadNameInputRef,
                    });
                }
            });
            onWillUnmount(function () {
                if (self.modelDropdownRef.el) {
                    self.modelDropdownRef.el.removeEventListener('shown.bs.dropdown', self._onModelDropdownShown);
                    self.modelDropdownRef.el.removeEventListener('hidden.bs.dropdown', self._onModelDropdownHidden);
                }
            });
            onPatched(function () {
                if (self.state.shouldShowDropdown) {
                    const dropdownContainer = self.modelDropdownRef.el;
                    if (dropdownContainer) {
                        const dropdownTrigger = $(dropdownContainer).find('[data-toggle="dropdown"], [data-bs-toggle="dropdown"]');
                        if (dropdownTrigger.length) {
                            dropdownTrigger.dropdown('show');
                        }
                    }
                    self.state.shouldShowDropdown = false;
                }
                if (self.state.shouldFocusSearch) {
                    if (self.modelSearchInputRef.el) {
                        self.modelSearchInputRef.el.focus();
                        self.state.shouldFocusSearch = false;
                    }
                }
            });
        }

        get llmChatThreadHeaderView() {
            return this.props.record;
        }

        get threadView() {
            return this.llmChatThreadHeaderView.threadView;
        }

        get thread() {
            const tv = this.threadView;
            return tv ? tv.thread : undefined;
        }

        get messaging() {
            return this.env.messaging;
        }

        get llmChat() {
            const t = this.thread;
            return t ? t.llmChat : undefined;
        }

        get llmProviders() {
            const c = this.llmChat;
            return c && c.llmProviders ? c.llmProviders : [];
        }

        get llmToolsList() {
            const c = this.llmChat;
            return c && c.tools ? c.tools : [];
        }

        get llmModels() {
            return this.llmChatThreadHeaderView.modelsAvailableToSelect;
        }

        get filteredModels() {
            const query = this.state.modelSearchQuery.trim().toLowerCase();
            if (!query) {
                return this.llmModels;
            }
            const self = this;
            return this.llmModels.filter(function (model) {
                return model.name.toLowerCase().includes(query);
            });
        }

        get isSmall() {
            const lc = this.llmChat;
            if (lc && lc.llmChatView) {
                return lc.llmChatView.isSmall;
            }
            return this.messaging.device.isSmall;
        }

        get showThreadListHamburger() {
            return this.isSmall || Boolean(this.llmChat && this.llmChat.isSystrayFloatingMode);
        }

        get useCompactHeaderIcons() {
            return Boolean(this.llmChat && this.llmChat.isSystrayFloatingMode);
        }

        get compactProviderTitle() {
            const sp = this.llmChatThreadHeaderView.selectedProvider;
            const n = sp && sp.name ? sp.name : this.env._t('Seleccionar proveedor');
            return this.env._t('Proveedor') + ': ' + n;
        }

        get compactModelTitle() {
            const sm = this.llmChatThreadHeaderView.selectedModel;
            const n = sm && sm.name ? sm.name : this.env._t('Seleccionar asistente');
            return this.env._t('Asistente') + ': ' + n;
        }

        get compactToolsTitle() {
            const n = this.thread && this.thread.selectedToolIds ? this.thread.selectedToolIds.length : 0;
            return this.env._t('Herramientas') + ' (' + n + ')';
        }

        get displayThreadName() {
            const thread = this.thread;
            if (!thread) {
                return '';
            }
            const raw = thread.name;
            if (raw !== undefined && raw !== null && String(raw).trim() !== '') {
                return String(raw).trim();
            }
            if (thread.id) {
                return 'Chat #' + thread.id;
            }
            return this.env._t('Chat');
        }

        onSelectProvider(provider) {
            if (provider.id !== this.llmChatThreadHeaderView.selectedProviderId) {
                const defaultModel = this.getDefaultModelForProvider(provider.id);
                this.llmChatThreadHeaderView.saveSelectedModel(defaultModel ? defaultModel.id : undefined);
                this.state.modelSearchQuery = '';
                this.state.shouldShowDropdown = true;
            }
        }

        getDefaultModelForProvider(providerId) {
            const llmChat = this.llmChat;
            const availableModels = (llmChat && llmChat.llmModels ? llmChat.llmModels : []).filter(function (model) {
                return model.llmProvider && model.llmProvider.id === providerId;
            });
            const defaultModel = availableModels.find(function (model) { return model.default; });
            if (defaultModel) {
                return defaultModel;
            }
            if (availableModels.length > 0) {
                return availableModels[0];
            }
            return null;
        }

        onSelectModel(model) {
            this.llmChatThreadHeaderView.saveSelectedModel(model.id);
            this.state.modelSearchQuery = '';
        }

        onModelSearchInput(ev) {
            this.state.modelSearchQuery = ev.target.value;
        }

        _preventDropdownClose(ev) {
            ev.stopPropagation();
        }

        _onModelDropdownShown() {
            const self = this;
            setTimeout(function () {
                if (self.modelSearchInputRef.el) {
                    self.modelSearchInputRef.el.focus();
                }
            }, 0);
        }

        _onModelDropdownHidden() {
            this.state.modelSearchQuery = '';
        }

        _onToggleThreadList() {
            const v = this.llmChat && this.llmChat.llmChatView;
            if (!v) {
                return;
            }
            v.update({
                isThreadListVisible: !v.isThreadListVisible,
            });
        }

        onKeyDownThreadNameInput(ev) {
            switch (ev.key) {
                case 'Enter':
                    ev.preventDefault();
                    this.llmChatThreadHeaderView.saveThreadName();
                    break;
                case 'Escape':
                    ev.preventDefault();
                    this.llmChatThreadHeaderView.discardThreadNameEdition();
                    break;
            }
        }

        onInputThreadNameInput(ev) {
            this.llmChatThreadHeaderView.update({ pendingName: ev.target.value });
        }

        async onToolSelectChange(ev, tool) {
            if (!this.thread) {
                return;
            }
            const checked = ev.target.checked;
            const currentSelectedIds = this.thread.selectedToolIds || [];
            const newSelectedToolIds = checked
                ? currentSelectedIds.concat([tool.id])
                : currentSelectedIds.filter(function (id) { return id !== tool.id; });

            await this.thread.updateLLMChatThreadSettings({
                toolIds: newSelectedToolIds,
            });

            this.thread.update({
                selectedToolIds: newSelectedToolIds,
            });
        }
    }

    Object.assign(LLMChatThreadHeader, {
        props: { record: Object },
        components: {
            LLMChatThreadRelatedRecord: LLMChatThreadRelatedRecord,
        },
        template: 'llm_thread.LLMChatThreadHeader',
    });

    return LLMChatThreadHeader;
});
