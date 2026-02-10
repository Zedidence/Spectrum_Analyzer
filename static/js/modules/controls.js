/**
 * UI control bindings.
 *
 * Connects DOM elements to state and WebSocket commands.
 * Handles frequency presets, gain slider, bandwidth, sample rate, FFT size,
 * DSP settings (window, averaging, DC removal, peak hold).
 */

export class Controls {
    /**
     * @param {StateStore} state - Reactive state store
     * @param {Connection} connection - WebSocket connection
     */
    constructor(state, connection) {
        this._state = state;
        this._conn = connection;

        // Cache DOM elements
        this._els = {
            startBtn: document.getElementById('start-btn'),
            stopBtn: document.getElementById('stop-btn'),
            frequency: document.getElementById('frequency'),
            bandwidth: document.getElementById('bandwidth'),
            gain: document.getElementById('gain'),
            gainValue: document.getElementById('gain-value'),
            sampleRate: document.getElementById('sample-rate-control'),
            fftSize: document.getElementById('fft-size-control'),
            checkDevice: document.getElementById('check-device-btn'),
            statusIndicator: document.getElementById('status-indicator'),
            statusText: document.getElementById('status-text'),
            deviceStatus: document.getElementById('device-status'),
            sampleRateDisplay: document.getElementById('sample-rate'),
            fftSizeDisplay: document.getElementById('fft-size'),
            updateRate: document.getElementById('update-rate'),
            peakFreq: document.getElementById('peak-freq'),
            peakPower: document.getElementById('peak-power'),
            waterfallHistory: document.getElementById('waterfall-history'),
            // DSP controls
            windowType: document.getElementById('window-type'),
            averagingMode: document.getElementById('averaging-mode'),
            averagingAlpha: document.getElementById('averaging-alpha'),
            averagingAlphaValue: document.getElementById('averaging-alpha-value'),
            averagingAlphaGroup: document.getElementById('averaging-alpha-group'),
            dcRemoval: document.getElementById('dc-removal'),
            peakHoldToggle: document.getElementById('peak-hold-toggle'),
            peakHoldReset: document.getElementById('peak-hold-reset'),
            // Display controls
            colormapSelect: document.getElementById('colormap-select'),
            autoScaleToggle: document.getElementById('auto-scale-toggle'),
            agcToggle: document.getElementById('agc-toggle'),
        };

        this._setupControls();
        this._setupDSPControls();
        this._setupDisplayControls();
        this._setupKeyboard();
        this._setupStateListeners();
    }

    _setupControls() {
        const { _els: els, _conn: conn, _state: state } = this;

        // Start/Stop
        els.startBtn.addEventListener('click', () => {
            conn.send('start');
            els.startBtn.disabled = true;
            els.stopBtn.disabled = false;
        });

        els.stopBtn.addEventListener('click', () => {
            conn.send('stop');
            els.startBtn.disabled = false;
            els.stopBtn.disabled = true;
        });

        // Frequency
        els.frequency.addEventListener('change', () => {
            const freqMHz = parseFloat(els.frequency.value);
            if (!isNaN(freqMHz) && freqMHz >= 20 && freqMHz <= 6000) {
                conn.send('set_frequency', { value: freqMHz * 1e6 });
            }
        });

        // Frequency presets
        document.querySelectorAll('.btn-preset').forEach(btn => {
            btn.addEventListener('click', () => {
                const freq = parseFloat(btn.dataset.freq);
                els.frequency.value = freq;
                conn.send('set_frequency', { value: freq * 1e6 });
            });
        });

        // Bandwidth
        els.bandwidth.addEventListener('change', () => {
            conn.send('set_bandwidth', { value: parseFloat(els.bandwidth.value) });
        });

        // Gain
        els.gain.addEventListener('input', () => {
            els.gainValue.textContent = els.gain.value;
        });
        els.gain.addEventListener('change', () => {
            conn.send('set_gain', { value: parseFloat(els.gain.value) });
        });

        // Sample rate
        els.sampleRate.addEventListener('change', () => {
            conn.send('set_sample_rate', { value: parseFloat(els.sampleRate.value) });
        });

        // FFT size
        els.fftSize.addEventListener('change', () => {
            conn.send('set_fft_size', { value: parseInt(els.fftSize.value) });
        });

        // Check device
        els.checkDevice.addEventListener('click', () => {
            els.deviceStatus.textContent = 'Checking...';
            els.deviceStatus.className = 'device-status-checking';
            conn.send('check_device');
        });
    }

    _setupDSPControls() {
        const { _els: els, _conn: conn } = this;

        // Window function
        els.windowType.addEventListener('change', () => {
            conn.send('set_dsp', { params: { window_type: els.windowType.value } });
        });

        // Averaging mode
        els.averagingMode.addEventListener('change', () => {
            const mode = els.averagingMode.value;
            conn.send('set_dsp', { params: { averaging_mode: mode } });
            // Show/hide alpha slider
            els.averagingAlphaGroup.style.display =
                mode === 'exponential' ? '' : 'none';
        });

        // Averaging alpha (smoothing)
        els.averagingAlpha.addEventListener('input', () => {
            els.averagingAlphaValue.textContent = els.averagingAlpha.value;
        });
        els.averagingAlpha.addEventListener('change', () => {
            conn.send('set_dsp', {
                params: { averaging_alpha: parseFloat(els.averagingAlpha.value) },
            });
        });

        // DC removal
        els.dcRemoval.addEventListener('change', () => {
            conn.send('set_dsp', { params: { dc_removal: els.dcRemoval.checked } });
        });

        // Peak hold
        els.peakHoldToggle.addEventListener('change', () => {
            const enabled = els.peakHoldToggle.checked;
            conn.send('set_dsp', { params: { peak_hold: enabled } });
            els.peakHoldReset.disabled = !enabled;
        });

        els.peakHoldReset.addEventListener('click', () => {
            conn.send('set_dsp', { params: { peak_hold_reset: true } });
        });

        // Initialize visibility of alpha group
        els.averagingAlphaGroup.style.display =
            els.averagingMode.value === 'exponential' ? '' : 'none';
    }

    _setupDisplayControls() {
        const { _els: els, _conn: conn, _state: state } = this;

        // Colormap
        els.colormapSelect.addEventListener('change', () => {
            state.set('colormap', els.colormapSelect.value);
        });

        // Auto-scale
        els.autoScaleToggle.addEventListener('change', () => {
            state.set('autoScale', els.autoScaleToggle.checked);
        });

        // AGC
        els.agcToggle.addEventListener('change', () => {
            conn.send('set_agc', { enabled: els.agcToggle.checked });
        });
    }

    _setupKeyboard() {
        document.addEventListener('keydown', (e) => {
            // Don't capture when typing in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

            switch (e.key) {
                case 'ArrowUp':
                    e.preventDefault();
                    this._adjustFrequency(1);
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    this._adjustFrequency(-1);
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    this._adjustFrequency(0.1);
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    this._adjustFrequency(-0.1);
                    break;
                case ' ':
                    e.preventDefault();
                    if (this._state.get('streaming')) {
                        this._els.stopBtn.click();
                    } else {
                        this._els.startBtn.click();
                    }
                    break;
            }
        });
    }

    _adjustFrequency(deltaMHz) {
        const el = this._els.frequency;
        let freq = parseFloat(el.value) + deltaMHz;
        freq = Math.max(20, Math.min(6000, freq));
        el.value = freq.toFixed(3);
        this._conn.send('set_frequency', { value: freq * 1e6 });
    }

    _setupStateListeners() {
        const els = this._els;

        // Connection status
        this._state.on('connected', (connected) => {
            els.statusIndicator.className = 'status-indicator ' +
                (connected ? 'connected' : 'disconnected');
            els.statusText.textContent = connected ? 'Connected' : 'Disconnected';
        });

        // Streaming status
        this._state.on('streaming', (streaming) => {
            els.startBtn.disabled = streaming;
            els.stopBtn.disabled = !streaming;
        });
    }

    /**
     * Update controls from a status message.
     * @param {Object} status
     */
    updateFromStatus(status) {
        const els = this._els;

        if (status.streaming !== undefined) {
            this._state.set('streaming', status.streaming);
        }

        if (status.center_freq !== undefined) {
            this._state.set('centerFreq', status.center_freq);
            els.frequency.value = (status.center_freq / 1e6).toFixed(3);
        }

        if (status.sample_rate !== undefined) {
            this._state.set('sampleRate', status.sample_rate);
            els.sampleRateDisplay.textContent =
                (status.sample_rate / 1e6).toFixed(2) + ' MS/s';
        }

        if (status.gain !== undefined) {
            this._state.set('gain', status.gain);
            els.gain.value = status.gain;
            els.gainValue.textContent = Math.round(status.gain);
        }

        if (status.bandwidth !== undefined) {
            this._state.set('bandwidth', status.bandwidth);
        }

        if (status.fft_size !== undefined) {
            this._state.set('fftSize', status.fft_size);
            els.fftSizeDisplay.textContent = status.fft_size;
        }

        if (status.device_connected !== undefined) {
            this._state.set('deviceConnected', status.device_connected);
            if (status.device_connected) {
                els.deviceStatus.textContent = 'Connected';
                els.deviceStatus.className = 'device-status-connected';
            } else {
                els.deviceStatus.textContent = status.device_error || 'Not found';
                els.deviceStatus.className = 'device-status-disconnected';
            }
        }
    }

    /**
     * Update display stats (FPS counter, peak info).
     * @param {Object} data - { fps, peakFreq, peakPower, waterfallLines }
     */
    updateStats(data) {
        const els = this._els;

        if (data.fps !== undefined && els.updateRate) {
            els.updateRate.textContent = data.fps + ' Hz';
        }

        if (data.peakFreq !== undefined && els.peakFreq) {
            els.peakFreq.textContent = 'Peak: ' + formatFreq(data.peakFreq);
        }

        if (data.peakPower !== undefined && els.peakPower) {
            els.peakPower.textContent = 'Power: ' + data.peakPower.toFixed(1) + ' dB';
        }

        if (data.waterfallLines !== undefined && els.waterfallHistory) {
            els.waterfallHistory.textContent = data.waterfallLines;
        }
    }
}

/**
 * Format frequency for display.
 * @param {number} freqHz
 * @returns {string}
 */
function formatFreq(freqHz) {
    if (freqHz >= 1e9) {
        return (freqHz / 1e9).toFixed(6) + ' GHz';
    } else if (freqHz >= 1e6) {
        return (freqHz / 1e6).toFixed(3) + ' MHz';
    } else if (freqHz >= 1e3) {
        return (freqHz / 1e3).toFixed(1) + ' kHz';
    }
    return freqHz.toFixed(0) + ' Hz';
}
