/**
 * Native WebSocket connection manager.
 *
 * Replaces Socket.IO entirely. Binary frames for spectrum data,
 * text frames for JSON commands/status.
 */

import { parseFrame } from './protocol.js';

export class Connection {
    /**
     * @param {Function} onSpectrum - Called with parsed spectrum data
     * @param {Function} onStatus - Called with status updates
     * @param {Function} onError - Called with error messages
     * @param {Function} [onSweep] - Called with sweep segment/panorama data
     * @param {Function} [onSignalEvent] - Called with signal detection events
     */
    constructor(onSpectrum, onStatus, onError, onSweep = null, onSignalEvent = null) {
        this._ws = null;
        this._onSpectrum = onSpectrum;
        this._onStatus = onStatus;
        this._onError = onError;
        this._onSweep = onSweep;
        this._onSignalEvent = onSignalEvent;
        this._reconnectDelay = 1000;
        this._maxReconnectDelay = 30000;
        this._shouldReconnect = true;
        this._connected = false;
        this._reconnectTimer = null;
    }

    /** Establish WebSocket connection. */
    connect() {
        // Cancel any pending reconnect timer
        if (this._reconnectTimer !== null) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }

        // Close old socket cleanly, nulling handlers to prevent stale callbacks
        if (this._ws) {
            this._ws.onclose = null;
            this._ws.onmessage = null;
            this._ws.onerror = null;
            this._ws.onopen = null;
            if (this._ws.readyState === WebSocket.OPEN ||
                this._ws.readyState === WebSocket.CONNECTING) {
                this._ws.close();
            }
        }

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws`;

        this._ws = new WebSocket(url);
        this._ws.binaryType = 'arraybuffer';

        this._ws.onopen = () => {
            console.log('WebSocket connected');
            this._connected = true;
            this._reconnectDelay = 1000;
            this._onStatus({ type: 'connection', connected: true });
        };

        this._ws.onclose = (event) => {
            console.log('WebSocket closed:', event.code);
            this._connected = false;
            this._onStatus({ type: 'connection', connected: false });

            if (this._shouldReconnect) {
                this._reconnectTimer = setTimeout(() => {
                    this._reconnectTimer = null;
                    this.connect();
                }, this._reconnectDelay);
                this._reconnectDelay = Math.min(
                    this._reconnectDelay * 1.5,
                    this._maxReconnectDelay
                );
            }
        };

        this._ws.onerror = () => {
            // onerror provides no useful info in browsers; onclose handles cleanup
        };

        this._ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                // Binary frame -> spectrum or sweep data
                const frame = parseFrame(event.data);
                if (frame) {
                    if (frame.type === 'spectrum') {
                        this._onSpectrum(frame);
                    } else if (frame.type === 'sweep_segment' || frame.type === 'sweep_panorama') {
                        if (this._onSweep) this._onSweep(frame);
                    }
                }
            } else {
                // Text frame -> JSON status/error
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'status') {
                        this._onStatus(msg.data);
                    } else if (msg.type === 'signal_event') {
                        if (this._onSignalEvent) this._onSignalEvent(msg.data);
                    } else if (msg.type === 'error') {
                        this._onError(msg.message || msg.data);
                    }
                } catch (e) {
                    console.error('Failed to parse text message:', e);
                }
            }
        };
    }

    /**
     * Send a command to the server.
     * @param {string} cmd - Command name
     * @param {Object} params - Additional parameters
     */
    send(cmd, params = {}) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify({ cmd, ...params }));
        }
    }

    /** Whether the WebSocket is currently connected. */
    get connected() {
        return this._connected;
    }

    /** Disconnect and stop reconnecting. */
    disconnect() {
        this._shouldReconnect = false;
        if (this._ws) {
            this._ws.close();
        }
    }
}
