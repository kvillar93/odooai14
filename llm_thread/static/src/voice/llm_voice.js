odoo.define('llm_thread/static/src/voice/llm_voice.js', function (require) {
    'use strict';

    /**
     * Dictado por voz compartido por el chat grande y el chat flotante.
     *
     * Como ChatGPT / Cursor: se graba con el micrófono mostrando una onda en
     * vivo, al confirmar se envía el audio a ``/llm/thread/transcribe`` y el
     * texto resultante se inserta en el compositor para revisarlo.
     */

    const { useState, onWillUnmount } = owl.hooks;

    var BAR_COUNT = 56;
    var MAX_SECONDS = 300;
    /** Altura mínima (%) de cada barra de la onda. */
    var MIN_BAR = 8;
    /**
     * Nivel (RMS escalado, 0-1) por debajo del cual la grabación se considera
     * silencio: no se envía, porque los modelos tienden a inventar texto.
     */
    var VOICE_THRESHOLD = 0.08;

    var dictationSupported = typeof navigator !== 'undefined' &&
        Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) &&
        typeof window.MediaRecorder !== 'undefined';

    function pickMimeType() {
        var types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
        for (var i = 0; i < types.length; i++) {
            if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) {
                return types[i];
            }
        }
        return '';
    }

    function emptyLevels() {
        var levels = [];
        for (var i = 0; i < BAR_COUNT; i++) {
            levels.push(MIN_BAR);
        }
        return levels;
    }

    function formatClock(seconds) {
        var s = Math.max(0, Math.floor(seconds));
        var rest = s % 60;
        return Math.floor(s / 60) + ':' + (rest < 10 ? '0' : '') + rest;
    }

    async function transcribeAudio(blob, threadId) {
        var form = new FormData();
        form.append('csrf_token', (typeof odoo !== 'undefined' && odoo.csrf_token) || '');
        if (threadId) {
            form.append('thread_id', threadId);
        }
        var ext = blob.type.indexOf('mp4') !== -1 ? 'm4a' : (blob.type.indexOf('ogg') !== -1 ? 'ogg' : 'webm');
        form.append('audio', blob, 'dictado.' + ext);
        var response = await fetch('/llm/thread/transcribe', {
            method: 'POST',
            body: form,
            credentials: 'include',
        });
        var data = {};
        try {
            data = await response.json();
        } catch (e) {
            // respuesta no JSON (p. ej. sesión caducada)
        }
        if (!response.ok || data.error) {
            throw new Error(data.error || response.statusText || 'Error de transcripción');
        }
        return (data.text || '').trim();
    }

    /**
     * @param {Object} options
     * @param {Function} options.getThreadId
     * @param {Function} options.onText texto transcrito
     * @param {Function} options.onError
     */
    function useDictation(options) {
        var state = useState({
            status: 'idle', // idle | recording | transcribing
            seconds: 0,
            clock: '0:00',
            levels: emptyLevels(),
        });
        var recorder = null;
        var stream = null;
        var audioCtx = null;
        var analyser = null;
        var chunks = [];
        var startedAt = 0;
        var timer = null;
        var raf = null;
        var lastSample = 0;
        var discard = false;
        var peak = null; // null = sin medidor (no se puede saber si hubo voz)

        function release() {
            clearInterval(timer);
            cancelAnimationFrame(raf);
            timer = raf = null;
            if (stream) {
                stream.getTracks().forEach(function (t) { t.stop(); });
            }
            if (audioCtx) {
                audioCtx.close().catch(function () {});
            }
            stream = audioCtx = analyser = null;
        }

        function sampleLevel(now) {
            raf = requestAnimationFrame(sampleLevel);
            // Contexto suspendido = lecturas planas: no cuentan como silencio.
            if (!analyser || !audioCtx || audioCtx.state !== 'running' || now - lastSample < 70) {
                return;
            }
            lastSample = now;
            var data = new Uint8Array(analyser.fftSize);
            analyser.getByteTimeDomainData(data);
            var sum = 0;
            for (var i = 0; i < data.length; i++) {
                var x = (data[i] - 128) / 128;
                sum += x * x;
            }
            var level = Math.min(1, Math.sqrt(sum / data.length) * 4);
            peak = Math.max(peak || 0, level);
            state.levels = state.levels.slice(1).concat([Math.max(MIN_BAR, Math.round(level * 100))]);
        }

        async function finish(mimeType) {
            release();
            var blob = new Blob(chunks, { type: mimeType.split(';')[0] });
            chunks = [];
            recorder = null;
            if (discard || !blob.size) {
                state.status = 'idle';
                return;
            }
            if (peak !== null && peak < VOICE_THRESHOLD) {
                state.status = 'idle';
                options.onError('No se detectó voz en la grabación.');
                return;
            }
            state.status = 'transcribing';
            var text = '';
            try {
                text = await transcribeAudio(blob, options.getThreadId());
            } catch (err) {
                state.status = 'idle';
                options.onError('No se pudo transcribir: ' + err.message);
                return;
            }
            // Primero se vuelve a mostrar el campo de texto y luego se inserta.
            state.status = 'idle';
            if (text) {
                options.onText(text);
            } else {
                options.onError('No se detectó voz en la grabación.');
            }
        }

        function stop() {
            if (recorder && recorder.state !== 'inactive') {
                recorder.stop();
            }
        }

        async function start() {
            if (state.status !== 'idle') {
                return;
            }
            try {
                stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (e) {
                options.onError('No se pudo acceder al micrófono. Revisa los permisos del navegador.');
                return;
            }
            var mimeType = pickMimeType();
            var current = mimeType ? new MediaRecorder(stream, { mimeType: mimeType }) : new MediaRecorder(stream);
            recorder = current;
            chunks = [];
            discard = false;
            peak = null;
            current.ondataavailable = function (ev) {
                if (ev.data && ev.data.size) {
                    chunks.push(ev.data);
                }
            };
            current.onstop = function () {
                finish(current.mimeType || mimeType || 'audio/webm');
            };
            try {
                var Ctx = window.AudioContext || window.webkitAudioContext;
                audioCtx = new Ctx();
                analyser = audioCtx.createAnalyser();
                analyser.fftSize = 512;
                audioCtx.createMediaStreamSource(stream).connect(analyser);
                if (audioCtx.resume) {
                    audioCtx.resume().catch(function () {});
                }
                raf = requestAnimationFrame(sampleLevel);
            } catch (e) {
                // La onda es decorativa: sin AudioContext se graba igual.
            }
            current.start(250);
            startedAt = Date.now();
            state.status = 'recording';
            state.seconds = 0;
            state.clock = '0:00';
            state.levels = emptyLevels();
            timer = setInterval(function () {
                state.seconds = (Date.now() - startedAt) / 1000;
                state.clock = formatClock(state.seconds);
                if (state.seconds >= MAX_SECONDS) {
                    stop();
                }
            }, 250);
        }

        function cancel() {
            discard = true;
            stop();
        }

        onWillUnmount(function () {
            discard = true;
            stop();
            release();
        });

        return {
            state: state,
            start: start,
            stop: stop,
            cancel: cancel,
        };
    }

    return {
        dictationSupported: dictationSupported,
        transcribeAudio: transcribeAudio,
        formatClock: formatClock,
        useDictation: useDictation,
    };
});
