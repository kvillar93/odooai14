odoo.define('llm_thread/static/src/models/llm_chat.js', function (require) {
    'use strict';

    const { registerNewModel, registerFieldPatchModel } = require('mail/static/src/model/model_core.js');
    const ModelField = require('mail/static/src/model/model_field.js');
    const { clear } = require('mail/static/src/model/model_field_command.js');
    const llmEnvUtils = require('llm_thread/static/src/js/llm_env_utils.js');

    const attr = ModelField.attr;
    const many2many = ModelField.many2many;
    const many2one = ModelField.many2one;
    const one2many = ModelField.one2many;
    const one2one = ModelField.one2one;

    const THREAD_SEARCH_FIELDS = [
        'name',
        'message_ids',
        'create_uid',
        'create_date',
        'write_date',
        'model_id',
        'provider_id',
        'model',
        'res_id',
        'tool_ids',
        'chat_window_id',
        'hide_thread_settings',
    ];

    function factory(dependencies) {

        class LLMChat extends dependencies['mail.model'] {

            close() {
                this.update({ llmChatView: clear() });
            }

            async openInitThread() {
                const Thread = this.env.models['mail.thread'];
                if (!this.initActiveId) {
                    if (this.threads.length > 0) {
                        await this.selectThread(this.threads[0].id);
                    }
                    return;
                }

                const parts = typeof this.initActiveId === 'number'
                    ? ['llm.thread', this.initActiveId]
                    : this.initActiveId.split('_');
                const model = parts[0];
                const threadId = Number(parts[1]);
                let thread = Thread.findFromIdentifyingData({
                    id: threadId,
                    model: model,
                });
                if (!thread) {
                    try {
                        const result = await this.async(() => this.env.services.rpc({
                            model: 'llm.thread',
                            method: 'search_read',
                            kwargs: {
                                domain: [['id', '=', threadId]],
                                fields: THREAD_SEARCH_FIELDS,
                            },
                        }));
                        if (result && result.length) {
                            const mapped = this._mapThreadDataFromServer(result[0]);
                            thread = Thread.insert(Object.assign({}, mapped, { llmChat: [['link', this]] }));
                        }
                    } catch (e) {
                        console.error('openInitThread', e);
                    }
                }
                if (!thread && this.threads.length > 0) {
                    await this.selectThread(this.threads[0].id);
                } else if (thread) {
                    await this.selectThread(thread.id);
                }
            }

            async openThread(thread) {
                this.update({ activeThread: [['link', thread]] });
                if (!this.llmChatView) {
                    this.env.bus.trigger('do-action', {
                        action: 'llm_thread.action_llm_chat',
                        options: {
                            name: this.env._t('Chat'),
                            active_id: this.threadToActiveId(thread),
                            clearBreadcrumbs: false,
                        },
                    });
                }
            }

            threadToActiveId(thread) {
                return thread.model + '_' + thread.id;
            }

            async loadThreads(additionalFields, domain) {
                additionalFields = additionalFields || [];
                domain = domain || [];
                const uid = this.env.session.uid;
                const defaultDomain = [['create_uid', '=', uid]];
                const scopeDomain = [];
                if (this.scopedChatWindowId) {
                    scopeDomain.push(['chat_window_id', '=', this.scopedChatWindowId]);
                }
                const finalDomain = defaultDomain.concat(scopeDomain).concat(domain);

                const result = await this.async(() => this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'search_read',
                    orderBy: [{name: 'write_date', asc: false}],
                    kwargs: {
                        domain: finalDomain,
                        fields: THREAD_SEARCH_FIELDS.concat(additionalFields),
                    },
                }));

                const Thread = this.env.models['mail.thread'];
                const threads = [];
                for (let i = 0; i < result.length; i++) {
                    const mapped = this._mapThreadDataFromServer(result[i]);
                    let thread = Thread.findFromIdentifyingData({
                        id: mapped.id,
                        model: mapped.model,
                    });
                    if (thread) {
                        thread.update(mapped);
                    } else {
                        thread = Thread.insert(Object.assign({}, mapped, { llmChat: [['link', this]] }));
                    }
                    threads.push(thread);
                }
                this.update({ threads: [['replace', threads]] });
            }

            _mapThreadDataFromServer(threadData) {
                const rawName = threadData.name;
                const safeName =
                    rawName !== undefined &&
                    rawName !== null &&
                    String(rawName).trim() !== ''
                        ? String(rawName).trim()
                        : 'New Chat #' + threadData.id;
                const mappedData = {
                    id: threadData.id,
                    model: 'llm.thread',
                    name: safeName,
                    message_needaction_counter: 0,
                    creator: threadData.create_uid
                        ? [['insert', { id: threadData.create_uid }]]
                        : undefined,
                    isServerPinned: true,
                    updatedAt: threadData.write_date,
                    relatedThreadModel: threadData.model,
                    relatedThreadId: threadData.res_id,
                    selectedToolIds: threadData.tool_ids || [],
                    promptId: threadData.prompt_id || null,
                    chatWindowId: (function () {
                        const cw = threadData.chat_window_id;
                        if (cw === undefined || cw === false || cw === null) {
                            return null;
                        }
                        if (Array.isArray(cw)) {
                            return cw[0];
                        }
                        return cw;
                    })(),
                    hideThreadSettings: Boolean(threadData.hide_thread_settings),
                };

                if (threadData.model_id && threadData.provider_id) {
                    mappedData.llmModel = [['insert', {
                        id: threadData.model_id[0],
                        name: threadData.model_id[1],
                        llmProvider: [['insert', {
                            id: threadData.provider_id[0],
                            name: threadData.provider_id[1],
                        }]],
                    }]];
                }

                return mappedData;
            }

            async refreshThread(threadId, additionalFields) {
                additionalFields = additionalFields || [];
                try {
                    const result = await this.async(() => this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'search_read',
                        kwargs: {
                            domain: [['id', '=', threadId]],
                            fields: THREAD_SEARCH_FIELDS.concat(additionalFields),
                        },
                    }));

                    if (!result || !result.length) {
                        return;
                    }

                    const mappedThreadData = this._mapThreadDataFromServer(result[0]);
                    const Thread = this.env.models['mail.thread'];
                    const threadRecord = Thread.findFromIdentifyingData({
                        id: threadId,
                        model: 'llm.thread',
                    });
                    if (threadRecord) {
                        threadRecord.update(mappedThreadData);
                    }
                } catch (error) {
                    console.error('Error refreshing thread:', error);
                }
            }

            async selectThread(threadId) {
                const Thread = this.env.models['mail.thread'];
                const thread = Thread.findFromIdentifyingData({
                    id: threadId,
                    model: 'llm.thread',
                });
                if (thread) {
                    await this.refreshThread(threadId);
                    this.update({ activeThread: [['link', thread]] });
                }
            }

            open() {
                this.update({ llmChatView: [['create', {}]] });
            }

            async loadLLMModels() {
                const result = await this.async(() => this.env.services.rpc({
                    model: 'llm.model',
                    method: 'search_read',
                    kwargs: {
                        domain: [],
                        fields: ['name', 'id', 'provider_id', 'default'],
                    },
                }));

                const LLMModel = this.env.models['mail.llm_model'];
                const records = [];
                for (let i = 0; i < result.length; i++) {
                    const model = result[i];
                    const data = {
                        id: model.id,
                        name: model.name,
                        llmProvider: model.provider_id
                            ? [['insert', { id: model.provider_id[0], name: model.provider_id[1] }]]
                            : clear(),
                        default: model.default,
                        llmChat: [['link', this]],
                    };
                    let rec = LLMModel.findFromIdentifyingData({ id: model.id });
                    if (rec) {
                        rec.update(data);
                    } else {
                        rec = LLMModel.insert(data);
                    }
                    records.push(rec);
                }
                this.update({ llmModels: [['replace', records]] });
            }

            async createThread(params) {
                const name = params.name;
                const relatedThreadModel = params.relatedThreadModel;
                const relatedThreadId = params.relatedThreadId;
                const defaultModel = this.defaultLLMModel;
                if (!defaultModel) {
                    llmEnvUtils.llmNotify(this.env, {
                        title: 'No hay modelo LLM',
                        message: 'Añada un modelo LLM para usar esta función',
                        type: 'warning',
                    });
                    throw new Error('No LLM model available');
                }

                const threadData = {
                    model_id: defaultModel.id,
                    provider_id: defaultModel.llmProvider.id,
                };
                if (
                    name !== undefined &&
                    name !== null &&
                    String(name).trim() !== ''
                ) {
                    threadData.name = name;
                }
                if (this.scopedChatWindowId) {
                    threadData.chat_window_id = this.scopedChatWindowId;
                }
                if (relatedThreadModel && relatedThreadId) {
                    threadData.model = relatedThreadModel;
                    threadData.res_id = relatedThreadId;
                }

                const threadId = await this.async(() => this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'create',
                    args: [threadData],
                }));

                const threadDetails = await this.async(() => this.env.services.rpc({
                    model: 'llm.thread',
                    method: 'read',
                    args: [[threadId], ['name', 'model_id', 'provider_id', 'write_date']],
                }));

                if (!threadDetails || !threadDetails[0]) {
                    llmEnvUtils.llmNotify(this.env, {
                        title: 'Error',
                        message: 'No se pudo crear el hilo',
                        type: 'danger',
                    });
                    return null;
                }

                const Thread = this.env.models['mail.thread'];
                const insertData = {
                    id: threadId,
                    model: 'llm.thread',
                    name: threadDetails[0].name,
                    message_needaction_counter: 0,
                    isServerPinned: true,
                    llmModel: defaultModel ? [['link', defaultModel]] : clear(),
                    llmChat: [['link', this]],
                    updatedAt: threadDetails[0].write_date,
                };
                if (this.scopedChatWindowId) {
                    insertData.chatWindowId = this.scopedChatWindowId;
                }
                if (relatedThreadModel) {
                    insertData.relatedThreadModel = relatedThreadModel;
                }
                if (relatedThreadId) {
                    insertData.relatedThreadId = relatedThreadId;
                }
                return Thread.insert(insertData);
            }

            async ensureDataLoaded() {
                if (this.llmModels.length === 0) {
                    await this.loadLLMModels();
                }
                if (!this.tools || this.tools.length === 0) {
                    await this.loadTools();
                }
            }

            async ensureThread(options) {
                options = options || {};
                const relatedThreadModel = options.relatedThreadModel;
                const relatedThreadId = options.relatedThreadId;
                const forceReload = options.forceReload === true;

                await this.ensureDataLoaded();

                const domain = [];
                if (relatedThreadModel && relatedThreadId) {
                    domain.push(['model', '=', relatedThreadModel]);
                    domain.push(['res_id', '=', relatedThreadId]);
                }

                const contextChanged = relatedThreadModel &&
                    (this.relatedThreadModel !== relatedThreadModel ||
                        this.relatedThreadId !== relatedThreadId);

                if (relatedThreadModel !== undefined || relatedThreadId !== undefined) {
                    this.update({
                        relatedThreadModel: relatedThreadModel || this.relatedThreadModel,
                        relatedThreadId: relatedThreadId !== undefined ? relatedThreadId : this.relatedThreadId,
                    });
                }

                if (this.threads.length === 0 || forceReload || contextChanged) {
                    await this.loadThreads([], domain);
                }

                if (relatedThreadModel && relatedThreadId) {
                    const existingThread = this.threads.find(
                        function (thread) {
                            return thread.relatedThreadModel === relatedThreadModel &&
                                thread.relatedThreadId === relatedThreadId;
                        }
                    );
                    if (existingThread) {
                        return existingThread;
                    }

                    try {
                        return await this.createThread({
                            relatedThreadModel: relatedThreadModel,
                            relatedThreadId: relatedThreadId,
                        });
                    } catch (error) {
                        console.error('Failed to create thread for related model:', error);
                    }
                }

                if (this.threads.length > 0) {
                    return this.threads[0];
                }

                try {
                    return await this.createThread({});
                } catch (error) {
                    console.error('Failed to create default thread:', error);
                    return null;
                }
            }

            async createNewThread() {
                try {
                    const thread = await this.createThread({});
                    if (thread) {
                        this.selectThread(thread.id);
                    }
                } catch (error) {
                    console.error('Failed to create new thread:', error);
                }
            }

            async initializeLLMChat(action, initActiveId, postInitializationPromises) {
                postInitializationPromises = postInitializationPromises || [];
                const winId =
                    (action.context && action.context.default_chat_window_id) ||
                    (action.params && action.params.default_chat_window_id) ||
                    null;
                const scopeKey = action.id + '|' + (winId != null ? String(winId) : '');
                const scopeChanged = this.chatInitScopeKey !== scopeKey;

                this.update({
                    relatedThreadModel: clear(),
                    relatedThreadId: clear(),
                    scopedChatWindowId: winId || clear(),
                    llmChatView: [['create', {
                        actionId: action.id,
                    }]],
                    initActiveId: initActiveId,
                });
                if (scopeChanged) {
                    this.update({ isInitThreadHandled: false, chatInitScopeKey: scopeKey });
                }

                await this.async(() => llmEnvUtils.waitMessagingReady(this.env));
                await this.loadLLMModels();
                await this.loadThreads();
                await this.loadTools();

                if (postInitializationPromises.length > 0) {
                    await Promise.all(postInitializationPromises);
                }

                if (!this.isInitThreadHandled) {
                    this.update({ isInitThreadHandled: true });
                    if (winId) {
                        await this.createThreadFromChatWindow(winId);
                    } else if (!this.activeThread) {
                        await this.openInitThread();
                    }
                }
                if (this.activeThread && this.activeThread.id) {
                    await this.refreshThread(this.activeThread.id);
                }
            }

            async createThreadFromChatWindow(windowId) {
                try {
                    await this.loadThreads([], []);
                    if (this.orderedThreads && this.orderedThreads.length > 0) {
                        await this.selectThread(this.orderedThreads[0].id);
                        return;
                    }
                    const threadId = await this.async(() => this.env.services.rpc({
                        model: 'llm.thread',
                        method: 'create',
                        args: [{ chat_window_id: windowId }],
                    }));
                    await this.loadThreads([], []);
                    await this.selectThread(threadId);
                } catch (e) {
                    console.error('createThreadFromChatWindow', e);
                    llmEnvUtils.llmNotify(this.env, {
                        message: this.env._t('No se pudo crear el chat desde la ventana.'),
                        type: 'danger',
                    });
                    await this.openInitThread();
                }
            }

            async loadTools() {
                try {
                    const result = await this.async(() => this.env.services.rpc({
                        model: 'llm.tool',
                        method: 'search_read',
                        kwargs: {
                            domain: [['active', '=', true]],
                            fields: ['name', 'id', 'default'],
                        },
                    }));

                    const LLMTool = this.env.models['mail.llm_tool'];
                    const records = [];
                    for (let i = 0; i < result.length; i++) {
                        const tool = result[i];
                        const data = {
                            id: tool.id,
                            name: tool.name,
                            default: Boolean(tool.default),
                            llmChat: [['link', this]],
                        };
                        let rec = LLMTool.findFromIdentifyingData({ id: tool.id });
                        if (rec) {
                            rec.update(data);
                        } else {
                            rec = LLMTool.insert(data);
                        }
                        records.push(rec);
                    }
                    this.update({ tools: [['replace', records]] });
                } catch (error) {
                    console.error('Error loading tools:', error);
                    return [];
                }
            }

            _computeOrderedThreads() {
                if (!this.threads || !this.threads.length) {
                    return clear();
                }
                const sorted = this.threads.slice().sort(function (a, b) {
                    const dateA = a.updatedAt
                        ? new Date(a.updatedAt.replace(' ', 'T'))
                        : new Date(0);
                    const dateB = b.updatedAt
                        ? new Date(b.updatedAt.replace(' ', 'T'))
                        : new Date(0);
                    return dateB - dateA;
                });
                return [['replace', sorted]];
            }

            _computeThreadCache() {
                if (!this.activeThread) {
                    return clear();
                }
                return [['link', this.activeThread.cache('[]')]];
            }
        }

        LLMChat.modelName = 'mail.llm_chat';

        LLMChat.fields = {
            activeId: attr({
                compute: '_computeActiveId',
                dependencies: ['activeThread'],
            }),
            llmChatView: one2one('mail.llm_chat_view', {
                inverse: 'llmChat',
                isCausal: true,
            }),
            isInitThreadHandled: attr({ default: false }),
            initActiveId: attr({ default: null }),
            activeThread: many2one('mail.thread', {
                inverse: 'activeLLMChat',
            }),
            threads: one2many('mail.thread', {
                inverse: 'llmChat',
            }),
            orderedThreads: many2many('mail.thread', {
                compute: '_computeOrderedThreads',
                dependencies: ['threads'],
                inverse: 'llmChatOrderedThreads',
            }),
            threadCache: many2one('mail.thread_cache', {
                compute: '_computeThreadCache',
                dependencies: ['activeThread'],
            }),
            llmModels: one2many('mail.llm_model', {
                inverse: 'llmChat',
            }),
            llmProviders: many2many('mail.llm_provider', {
                compute: '_computeLlmProviders',
                dependencies: ['llmModels'],
                inverse: 'llmChats',
            }),
            defaultLLMModel: many2one('mail.llm_model', {
                compute: '_computeDefaultLLMModel',
                dependencies: ['llmModels', 'activeThread'],
            }),
            tools: one2many('mail.llm_tool', {
                inverse: 'llmChat',
            }),
            llmAnalyzingToolName: attr({ default: null }),
            scopedChatWindowId: attr({ default: null }),
            chatInitScopeKey: attr({ default: '' }),
            isSystrayFloatingMode: attr({ default: false }),
            relatedThreadModel: attr(),
            relatedThreadId: attr(),
            isChatterMode: attr({
                compute: '_computeIsChatterMode',
                dependencies: ['relatedThreadModel', 'relatedThreadId'],
            }),
            messaging: one2one('mail.messaging', {
                inverse: 'llmChat',
            }),
        };

        LLMChat.prototype._computeActiveId = function () {
            return this.activeThread
                ? this.threadToActiveId(this.activeThread)
                : clear();
        };

        LLMChat.prototype._computeIsChatterMode = function () {
            return Boolean(this.relatedThreadModel && this.relatedThreadId);
        };

        LLMChat.prototype._computeLlmProviders = function () {
            if (!this.llmModels || !this.llmModels.length) {
                return [['replace', []]];
            }
            const providers = this.llmModels
                .map(function (m) { return m && m.llmProvider ? m.llmProvider : null; })
                .filter(function (p) { return p && p.id; });
            const uniq = [];
            const seen = {};
            providers.forEach(function (p) {
                if (!seen[p.id]) {
                    seen[p.id] = true;
                    uniq.push(p);
                }
            });
            return [['replace', uniq]];
        };

        LLMChat.prototype._computeDefaultLLMModel = function () {
            if (!this.llmModels || !this.llmModels.length) {
                return clear();
            }
            const activeModel = this.activeThread && this.activeThread.llmModel;
            if (activeModel) {
                const found = this.llmModels.find(function (m) { return m && m.id === activeModel.id; });
                return found ? [['link', found]] : clear();
            }
            const markedDefault = this.llmModels.find(function (m) { return m && m.default; });
            if (markedDefault) {
                return [['link', markedDefault]];
            }
            return this.llmModels[0] ? [['link', this.llmModels[0]]] : clear();
        };

        return LLMChat;
    }

    registerNewModel('mail.llm_chat', factory);

    // Parche de mail.messaging en el mismo módulo que registra mail.llm_chat (orden seguro).
    registerFieldPatchModel('mail.messaging', 'llm_thread/static/src/models/llm_chat.js', {
        llmChat: one2one('mail.llm_chat', {
            default: [['create']],
            inverse: 'messaging',
            isCausal: true,
        }),
        llmChatActiveThread: many2one('mail.thread', {
            related: 'llmChat.activeThread',
        }),
    });
});
