/**
 * Reactive state store with change notification.
 *
 * Replaces the IIFE AppState module. Any module can subscribe
 * to state changes for reactive UI updates.
 */

export class StateStore {
    constructor() {
        this._state = {
            // Connection
            connected: false,

            // Streaming
            streaming: false,

            // Hardware params
            centerFreq: 100e6,
            sampleRate: 2e6,
            bandwidth: 2e6,
            gain: 40,
            fftSize: 2048,

            // Display params — tuned for BladeRF 2.0 typical output
            dbMin: -100,
            dbMax: -20,

            // Stats
            fps: 0,
            noiseFloor: -100,
            peakPower: -100,
            peakFreq: 0,

            // Device
            deviceConnected: false,
            deviceInfo: null,

            // Sweep
            sweepMode: 'off',       // 'off', 'survey', 'band_monitor'
            sweepRunning: false,
            sweepProgress: 0,        // 0.0 to 1.0
            sweepFreqStart: 47e6,
            sweepFreqEnd: 6e9,

            // Recording / Playback
            playbackActive: false,
            iqRecording: false,
        };

        this._listeners = new Map();
    }

    /**
     * Get a state value.
     * @param {string} key
     * @returns {*}
     */
    get(key) {
        return this._state[key];
    }

    /**
     * Set a state value and notify listeners.
     * @param {string} key
     * @param {*} value
     */
    set(key, value) {
        const old = this._state[key];
        if (old === value) return;
        this._state[key] = value;

        const callbacks = this._listeners.get(key);
        if (callbacks) {
            for (const cb of callbacks) {
                cb(value, old, key);
            }
        }
    }

    /**
     * Fire an action (always triggers listeners, even with same value).
     * Use for one-shot events like dB range adjustment.
     * @param {string} key
     * @param {*} value
     */
    fire(key, value) {
        this._state[key] = value;
        const callbacks = this._listeners.get(key);
        if (callbacks) {
            for (const cb of callbacks) {
                cb(value, undefined, key);
            }
        }
    }

    /**
     * Subscribe to state changes.
     * @param {string} key
     * @param {Function} callback - (newValue, oldValue, key) => void
     * @returns {Function} unsubscribe function
     */
    on(key, callback) {
        if (!this._listeners.has(key)) {
            this._listeners.set(key, new Set());
        }
        this._listeners.get(key).add(callback);
        return () => this._listeners.get(key)?.delete(callback);
    }

    /**
     * Batch update multiple keys, firing listeners after all are set.
     * @param {Object} updates - key-value pairs to update
     */
    batch(updates) {
        const changes = [];
        for (const [key, value] of Object.entries(updates)) {
            const old = this._state[key];
            if (old !== value) {
                this._state[key] = value;
                changes.push([key, value, old]);
            }
        }
        for (const [key, value, old] of changes) {
            const callbacks = this._listeners.get(key);
            if (callbacks) {
                for (const cb of callbacks) {
                    cb(value, old, key);
                }
            }
        }
    }
}
