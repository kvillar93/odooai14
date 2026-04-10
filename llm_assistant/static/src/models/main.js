odoo.define('llm_assistant/static/src/models/main.js', function (require) {
    'use strict';

    // Antes que cualquier modelo que referencie mail.llm_chat (p. ej. llm_assistant_record).
    require('llm_thread/static/src/models/llm_chat.js');

    require('llm_assistant/static/src/models/llm_prompt.js');
    require('llm_assistant/static/src/models/llm_assistant_record.js');
    require('llm_assistant/static/src/models/thread.js');
    require('llm_assistant/static/src/models/llm_chat.js');
    require('llm_assistant/static/src/models/llm_chat_thread_header_view.js');
});
