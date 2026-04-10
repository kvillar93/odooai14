odoo.define('llm_thread/static/src/models/main.js', function (require) {
    'use strict';

    require('llm_thread/static/src/js/llm_env_utils.js');
    require('llm_thread/static/src/models/llm_provider.js');
    require('llm_thread/static/src/models/llm_model.js');
    require('llm_thread/static/src/models/llm_tool.js');
    require('llm_thread/static/src/models/llm_chat.js');
    require('llm_thread/static/src/models/thread.js');
    require('llm_thread/static/src/models/thread_viewer_llm.js');
    require('llm_thread/static/src/models/llm_chat_view.js');
    require('llm_thread/static/src/models/llm_chat_thread_header_view.js');
    require('llm_thread/static/src/models/composer.js');
    require('llm_thread/static/src/models/thread_view.js');
    require('llm_thread/static/src/models/chatter.js');
    require('llm_thread/static/src/models/message.js');
    require('llm_thread/static/src/models/message_action.js');
    require('llm_thread/static/src/models/message_action_list.js');
    require('llm_thread/static/src/models/message_action_view.js');
    require('llm_thread/static/src/models/messaging_notification_handler.js');
});
