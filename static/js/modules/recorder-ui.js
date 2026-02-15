/**
 * Recording and playback UI controller.
 *
 * Manages IQ recording, spectrum recording, playback controls,
 * and recording file list.
 */

export class RecorderUI {
    /**
     * @param {HTMLElement} container - The #recording-container element
     * @param {Object} connection - Connection instance for WebSocket commands
     * @param {Object} state - StateStore instance
     */
    constructor(container, connection, state) {
        this._container = container;
        this._conn = connection;
        this._state = state;

        // Internal state
        this._iqRecording = false;
        this._spectrumRecording = false;
        this._playbackActive = false;
        this._playbackPaused = false;
        this._recordings = [];

        // Cache DOM refs
        this._els = {
            // IQ Recording
            iqRecordBtn: container.querySelector('#iq-record-btn'),
            iqStopBtn: container.querySelector('#iq-stop-btn'),
            iqStatus: container.querySelector('#iq-record-status'),

            // Spectrum Recording
            specRecordBtn: container.querySelector('#spec-record-btn'),
            specStopBtn: container.querySelector('#spec-stop-btn'),
            specStatus: container.querySelector('#spec-record-status'),

            // Playback
            playbackControls: container.querySelector('#playback-controls'),
            playbackStatus: container.querySelector('#playback-status'),
            playbackProgress: container.querySelector('#playback-progress'),
            playbackTime: container.querySelector('#playback-time'),
            playbackSpeedSelect: container.querySelector('#playback-speed'),
            playbackPauseBtn: container.querySelector('#playback-pause-btn'),
            playbackStopBtn: container.querySelector('#playback-stop-btn'),
            playbackLoopToggle: container.querySelector('#playback-loop'),

            // File list
            recordingsList: container.querySelector('#recordings-list'),
            refreshBtn: container.querySelector('#recordings-refresh-btn'),
            storageInfo: container.querySelector('#storage-info'),
        };

        this._setupControls();
        this._refreshList();
    }

    _setupControls() {
        const { _els: els, _conn: conn } = this;

        // IQ Recording
        if (els.iqRecordBtn) {
            els.iqRecordBtn.addEventListener('click', () => {
                conn.send('rec_iq_start');
            });
        }
        if (els.iqStopBtn) {
            els.iqStopBtn.addEventListener('click', () => {
                conn.send('rec_iq_stop');
                // Refresh list after stop to show the new file
                setTimeout(() => this._refreshList(), 500);
            });
        }

        // Spectrum Recording
        if (els.specRecordBtn) {
            els.specRecordBtn.addEventListener('click', () => {
                conn.send('rec_spectrum_start');
            });
        }
        if (els.specStopBtn) {
            els.specStopBtn.addEventListener('click', () => {
                conn.send('rec_spectrum_stop');
                setTimeout(() => this._refreshList(), 500);
            });
        }

        // Playback controls
        if (els.playbackPauseBtn) {
            els.playbackPauseBtn.addEventListener('click', () => {
                if (this._playbackPaused) {
                    conn.send('playback_resume');
                } else {
                    conn.send('playback_pause');
                }
            });
        }
        if (els.playbackStopBtn) {
            els.playbackStopBtn.addEventListener('click', () => {
                conn.send('playback_stop');
            });
        }
        if (els.playbackSpeedSelect) {
            els.playbackSpeedSelect.addEventListener('change', () => {
                conn.send('playback_speed', {
                    value: parseFloat(els.playbackSpeedSelect.value),
                });
            });
        }
        if (els.playbackLoopToggle) {
            els.playbackLoopToggle.addEventListener('change', () => {
                conn.send('playback_loop', {
                    enabled: els.playbackLoopToggle.checked,
                });
            });
        }

        // Refresh button
        if (els.refreshBtn) {
            els.refreshBtn.addEventListener('click', () => {
                this._refreshList();
            });
        }
    }

    _refreshList() {
        this._conn.send('rec_list');
    }

    /**
     * Update from server status message.
     * Called on every status update from the WebSocket.
     */
    updateFromStatus(status) {
        const els = this._els;

        // IQ Recording state
        if (status.iq_recording !== undefined) {
            this._iqRecording = status.iq_recording;
            if (els.iqRecordBtn) els.iqRecordBtn.disabled = status.iq_recording;
            if (els.iqStopBtn) els.iqStopBtn.disabled = !status.iq_recording;
            if (els.iqStatus) {
                els.iqStatus.textContent = status.iq_recording
                    ? `Recording: ${this._formatSize(status.iq_bytes_written || 0)}`
                    : '';
            }
        }

        // Spectrum Recording state
        if (status.spectrum_recording !== undefined) {
            this._spectrumRecording = status.spectrum_recording;
            if (els.specRecordBtn) els.specRecordBtn.disabled = status.spectrum_recording;
            if (els.specStopBtn) els.specStopBtn.disabled = !status.spectrum_recording;
            if (els.specStatus) {
                els.specStatus.textContent = status.spectrum_recording
                    ? `Frames: ${status.spectrum_frames || 0}`
                    : '';
            }
        }

        // Playback state
        if (status.playback_active !== undefined) {
            this._playbackActive = status.playback_active;
            this._playbackPaused = status.playback_paused || false;

            if (els.playbackControls) {
                els.playbackControls.style.display =
                    status.playback_active ? '' : 'none';
            }
            if (els.playbackPauseBtn) {
                els.playbackPauseBtn.textContent =
                    status.playback_paused ? 'Resume' : 'Pause';
            }
            if (els.playbackProgress && status.playback_progress !== undefined) {
                els.playbackProgress.style.width =
                    (status.playback_progress * 100).toFixed(1) + '%';
            }
            if (els.playbackTime) {
                const pos = (status.playback_position || 0).toFixed(1);
                const dur = (status.playback_duration || 0).toFixed(1);
                els.playbackTime.textContent = `${pos}s / ${dur}s`;
            }
            if (els.playbackStatus && status.playback_filename) {
                els.playbackStatus.textContent = status.playback_filename;
            }
        }

        // File list
        if (status.recordings !== undefined) {
            this._recordings = status.recordings;
            this._renderList();
        }

        // Storage info
        if (status.storage !== undefined) {
            if (els.storageInfo) {
                els.storageInfo.textContent =
                    `${status.storage.storage_used_display} / ` +
                    `${status.storage.storage_limit_display} ` +
                    `(${status.storage.storage_percent.toFixed(0)}%)`;
            }
        }
    }

    _renderList() {
        const el = this._els.recordingsList;
        if (!el) return;

        if (this._recordings.length === 0) {
            el.innerHTML = '<div class="signal-empty">No recordings</div>';
            return;
        }

        const html = this._recordings.map(rec => {
            const meta = rec.metadata || {};
            const isIQ = rec.type === 'iq';
            const badge = isIQ ? 'badge-live' : 'badge-sweep';
            const label = isIQ ? 'IQ' : 'SPEC';
            const freq = meta.center_freq
                ? this._formatFreq(meta.center_freq) : '--';
            const dur = meta.duration_seconds
                ? meta.duration_seconds.toFixed(1) + 's'
                : (meta.total_frames ? meta.total_frames + ' frames' : '--');

            return `<div class="recording-item" data-filename="${this._escapeAttr(rec.filename)}">
                <div class="recording-header">
                    <span class="${badge}">${label}</span>
                    <span class="recording-name">${this._escapeHtml(rec.filename)}</span>
                </div>
                <div class="recording-details">
                    <span>${freq}</span>
                    <span>${dur}</span>
                    <span>${rec.size_display}</span>
                </div>
                <div class="recording-actions">
                    ${isIQ ? `<button class="btn-small rec-play-btn"
                        data-filename="${this._escapeAttr(rec.filename)}">Play</button>` : ''}
                    <a class="rec-download-btn"
                        href="/api/recordings/${encodeURIComponent(rec.filename)}"
                        download>Download</a>
                    <button class="btn-small rec-delete-btn"
                        data-filename="${this._escapeAttr(rec.filename)}">Delete</button>
                </div>
            </div>`;
        }).join('');

        el.innerHTML = html;

        // Bind play buttons
        el.querySelectorAll('.rec-play-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._conn.send('playback_start', {
                    filename: btn.dataset.filename,
                });
            });
        });

        // Bind delete buttons
        el.querySelectorAll('.rec-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (confirm('Delete this recording?')) {
                    this._conn.send('rec_delete', {
                        filename: btn.dataset.filename,
                    });
                    setTimeout(() => this._refreshList(), 500);
                }
            });
        });
    }

    _formatSize(bytes) {
        if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
        if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
        if (bytes >= 1e3) return (bytes / 1e3).toFixed(0) + ' KB';
        return bytes + ' B';
    }

    _formatFreq(hz) {
        if (hz >= 1e9) return (hz / 1e9).toFixed(3) + ' GHz';
        if (hz >= 1e6) return (hz / 1e6).toFixed(3) + ' MHz';
        return (hz / 1e3).toFixed(1) + ' kHz';
    }

    _escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    _escapeAttr(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;');
    }
}
