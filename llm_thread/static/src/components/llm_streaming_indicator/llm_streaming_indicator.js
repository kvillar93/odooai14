odoo.define('llm_thread/static/src/components/llm_streaming_indicator/llm_streaming_indicator.js', function (require) {
    'use strict';

    const useShouldUpdateBasedOnProps = require('mail/static/src/component_hooks/use_should_update_based_on_props/use_should_update_based_on_props.js');

    const { Component } = owl;
    const { useState } = owl.hooks;

    class LLMStreamingIndicator extends Component {
        constructor(...args) {
            super(...args);
            useShouldUpdateBasedOnProps();
            this.state = useState({ dots: '' });
            this._interval = null;
        }

        mounted() {
            const self = this;
            let count = 0;
            this._interval = setInterval(function () {
                count = (count + 1) % 4;
                self.state.dots = '.'.repeat(count);
            }, 500);
        }

        willUnmount() {
            if (this._interval) {
                clearInterval(this._interval);
            }
        }
    }

    Object.assign(LLMStreamingIndicator, {
        template: 'llm_thread.LLMStreamingIndicator',
    });

    return LLMStreamingIndicator;
});
