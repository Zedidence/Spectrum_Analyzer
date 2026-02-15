/**
 * Signal detection UI manager.
 *
 * Maintains a list of detected signals, renders them in a scrollable
 * panel, and provides controls for detection enable/disable and
 * threshold adjustment.
 */

export class SignalList {
    /**
     * @param {HTMLElement} container - The signal list container element
     * @param {Object} connection - Connection instance for sending commands
     */
    constructor(container, connection) {
        this._container = container;
        this._connection = connection;

        // Signal state
        this._signals = new Map();  // signal_id -> signal data
        this._enabled = false;

        // DOM refs
        this._enableToggle = container.querySelector('#detection-toggle');
        this._thresholdInput = container.querySelector('#detection-threshold');
        this._thresholdValue = container.querySelector('#detection-threshold-value');
        this._signalCount = container.querySelector('#signal-count');
        this._listEl = container.querySelector('#signal-list-items');

        this._setupControls();
    }

    _setupControls() {
        if (this._enableToggle) {
            this._enableToggle.addEventListener('change', () => {
                this._enabled = this._enableToggle.checked;
                this._connection.send('detection_enable', {
                    enabled: this._enabled,
                });
            });
        }

        if (this._thresholdInput) {
            this._thresholdInput.addEventListener('input', () => {
                const val = parseFloat(this._thresholdInput.value);
                if (this._thresholdValue) {
                    this._thresholdValue.textContent = val.toFixed(0);
                }
            });
            this._thresholdInput.addEventListener('change', () => {
                const val = parseFloat(this._thresholdInput.value);
                this._connection.send('detection_set', {
                    params: { threshold_db: val },
                });
            });
        }
    }

    /**
     * Handle a signal event from the server.
     * @param {Object} data - { event, signal_id, center_freq, ... }
     */
    handleEvent(data) {
        const { event: eventType } = data;

        if (eventType === 'signal_new' || eventType === 'signal_update') {
            this._signals.set(data.signal_id, data);
        } else if (eventType === 'signal_lost') {
            this._signals.delete(data.signal_id);
        }

        this._render();
    }

    /**
     * Update from server status (initial load / reconnect).
     */
    updateFromStatus(status) {
        if (status.detection_enabled !== undefined) {
            this._enabled = status.detection_enabled;
            if (this._enableToggle) {
                this._enableToggle.checked = this._enabled;
            }
        }
        if (status.threshold_db !== undefined && this._thresholdInput) {
            this._thresholdInput.value = status.threshold_db;
            if (this._thresholdValue) {
                this._thresholdValue.textContent =
                    status.threshold_db.toFixed(0);
            }
        }
        if (status.tracked_signals !== undefined && this._signalCount) {
            this._signalCount.textContent = status.tracked_signals;
        }
    }

    /**
     * Get currently tracked signals for overlay rendering.
     * @returns {Array} Array of signal objects
     */
    getSignals() {
        return Array.from(this._signals.values());
    }

    _render() {
        if (!this._listEl) return;

        if (this._signalCount) {
            this._signalCount.textContent = this._signals.size;
        }

        if (this._signals.size === 0) {
            this._listEl.innerHTML =
                '<div class="signal-empty">No signals detected</div>';
            return;
        }

        // Sort by power (strongest first)
        const sorted = Array.from(this._signals.values())
            .sort((a, b) => b.peak_power - a.peak_power);

        const html = sorted.map(sig => {
            const freq = this._formatFreq(sig.center_freq);
            const bw = this._formatBW(sig.bandwidth);
            const cls = sig.classification
                ? `<span class="signal-class">${this._escapeHtml(sig.classification)}</span>`
                : '';

            return `<div class="signal-item" data-id="${sig.signal_id}">
                <div class="signal-freq">${freq} ${cls}</div>
                <div class="signal-details">
                    <span>${sig.peak_power.toFixed(1)} dB</span>
                    <span>BW: ${bw}</span>
                    <span>Hits: ${sig.hit_count}</span>
                </div>
            </div>`;
        }).join('');

        this._listEl.innerHTML = html;
    }

    _formatFreq(hz) {
        if (hz >= 1e9) return (hz / 1e9).toFixed(4) + ' GHz';
        if (hz >= 1e6) return (hz / 1e6).toFixed(3) + ' MHz';
        if (hz >= 1e3) return (hz / 1e3).toFixed(1) + ' kHz';
        return hz.toFixed(0) + ' Hz';
    }

    _formatBW(hz) {
        if (hz >= 1e6) return (hz / 1e6).toFixed(2) + ' MHz';
        if (hz >= 1e3) return (hz / 1e3).toFixed(1) + ' kHz';
        return hz.toFixed(0) + ' Hz';
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}
