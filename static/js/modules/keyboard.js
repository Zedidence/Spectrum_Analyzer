/**
 * Enhanced keyboard shortcut handler.
 *
 * Shortcuts (when not focused on input):
 *   Space      - Start/stop streaming
 *   Arrows     - Adjust frequency
 *   M          - Add marker at peak in view
 *   N          - Next peak search
 *   D          - Add delta marker
 *   C          - Clear all markers
 *   H          - Toggle peak hold
 *   R          - Reset zoom
 *   A          - Toggle auto-scale dB
 *   +/-        - Adjust dB range
 *   S          - Toggle signal detection
 *   W          - Start sweep (current mode)
 *   Escape     - Return to live mode (stop sweep/playback)
 *   ?          - Show keyboard shortcut help
 */

export class KeyboardHandler {
    /**
     * @param {Object} deps - Dependencies
     * @param {StateStore} deps.state
     * @param {Connection} deps.connection
     * @param {ZoomController} deps.zoom
     * @param {MarkerManager} deps.markers
     * @param {Function} deps.getSpectrum - Returns current spectrum data
     * @param {Function} deps.getCenterFreq
     * @param {Function} deps.getSampleRate
     */
    constructor(deps) {
        this._deps = deps;
        this._init();
    }

    _init() {
        document.addEventListener('keydown', (e) => {
            // Don't capture when typing in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

            this._handleKey(e);
        });
    }

    _handleKey(e) {
        const { state, connection, zoom, markers, getSpectrum, getCenterFreq, getSampleRate } = this._deps;

        switch (e.key.toLowerCase()) {
            case 'm':
                e.preventDefault();
                if (markers && getSpectrum()) {
                    markers.peakSearch(
                        getSpectrum(),
                        getCenterFreq(),
                        getSampleRate(),
                        zoom ? zoom.viewStart : 0,
                        zoom ? zoom.viewEnd : 1,
                    );
                }
                break;

            case 'n':
                e.preventDefault();
                if (markers && getSpectrum()) {
                    markers.nextPeakSearch(
                        getSpectrum(),
                        getCenterFreq(),
                        getSampleRate(),
                    );
                }
                break;

            case 'd':
                e.preventDefault();
                if (markers && markers.count > 0 && getSpectrum()) {
                    // Set last marker as reference, find next peak as delta
                    const lastMarker = markers.markers[markers.markers.length - 1];
                    markers.setReference(lastMarker.id);
                    const peak = markers.nextPeakSearch(
                        getSpectrum(),
                        getCenterFreq(),
                        getSampleRate(),
                    );
                    if (peak) {
                        // Convert to delta marker
                        peak.isDelta = true;
                        peak.refId = lastMarker.id;
                        peak.deltaFreq = peak.freq - lastMarker.freq;
                        peak.deltaPower = peak.power - lastMarker.power;
                    }
                }
                break;

            case 'c':
                e.preventDefault();
                if (markers) {
                    markers.clearMarkers();
                }
                break;

            case 'h':
                e.preventDefault();
                {
                    const toggle = document.getElementById('peak-hold-toggle');
                    if (toggle) {
                        toggle.checked = !toggle.checked;
                        toggle.dispatchEvent(new Event('change'));
                    }
                }
                break;

            case 'r':
                e.preventDefault();
                if (zoom) {
                    zoom.reset();
                }
                break;

            case 'a':
                e.preventDefault();
                {
                    const current = state.get('autoScale');
                    const newVal = !current;
                    state.set('autoScale', newVal);
                    // Sync the checkbox UI
                    const toggle = document.getElementById('auto-scale-toggle');
                    if (toggle) toggle.checked = newVal;
                }
                break;

            case '+':
            case '=':
                e.preventDefault();
                state.fire('dbRangeAdjust', 'narrow');
                break;

            case '-':
                e.preventDefault();
                state.fire('dbRangeAdjust', 'widen');
                break;

            case 's':
                e.preventDefault();
                {
                    const toggle = document.getElementById('detection-toggle');
                    if (toggle) {
                        toggle.checked = !toggle.checked;
                        toggle.dispatchEvent(new Event('change'));
                    }
                }
                break;

            case 'w':
                e.preventDefault();
                {
                    const sweepBtn = document.getElementById('sweep-start-btn');
                    if (sweepBtn && !sweepBtn.disabled) {
                        sweepBtn.click();
                    }
                }
                break;

            case 'escape':
                e.preventDefault();
                // Close help overlay if open
                {
                    const helpOverlay = document.getElementById('shortcut-help-overlay');
                    if (helpOverlay) {
                        helpOverlay.remove();
                        break;
                    }
                }
                // Stop sweep if running
                if (state.get('sweepRunning')) {
                    connection.send('sweep_stop');
                }
                // Stop playback if active
                if (state.get('playbackActive')) {
                    connection.send('playback_stop');
                }
                break;

            case '?':
                e.preventDefault();
                this._toggleHelp();
                break;
        }
    }

    _toggleHelp() {
        let overlay = document.getElementById('shortcut-help-overlay');
        if (overlay) {
            overlay.remove();
            return;
        }

        overlay = document.createElement('div');
        overlay.id = 'shortcut-help-overlay';
        overlay.className = 'shortcut-help-overlay';
        overlay.innerHTML = `
            <div class="shortcut-help-panel">
                <h3>Keyboard Shortcuts</h3>
                <div class="shortcut-grid">
                    <div class="shortcut-group">
                        <h4>General</h4>
                        <div class="shortcut-row"><kbd>Space</kbd><span>Start / Stop streaming</span></div>
                        <div class="shortcut-row"><kbd>Esc</kbd><span>Return to live mode</span></div>
                        <div class="shortcut-row"><kbd>?</kbd><span>Toggle this help</span></div>
                    </div>
                    <div class="shortcut-group">
                        <h4>Tuning</h4>
                        <div class="shortcut-row"><kbd>&uarr;</kbd> <kbd>&darr;</kbd><span>Adjust frequency</span></div>
                        <div class="shortcut-row"><kbd>A</kbd><span>Toggle auto-scale dB</span></div>
                        <div class="shortcut-row"><kbd>+</kbd> <kbd>-</kbd><span>Adjust dB range</span></div>
                    </div>
                    <div class="shortcut-group">
                        <h4>Markers</h4>
                        <div class="shortcut-row"><kbd>M</kbd><span>Add marker at peak</span></div>
                        <div class="shortcut-row"><kbd>N</kbd><span>Next peak search</span></div>
                        <div class="shortcut-row"><kbd>D</kbd><span>Delta marker</span></div>
                        <div class="shortcut-row"><kbd>C</kbd><span>Clear all markers</span></div>
                    </div>
                    <div class="shortcut-group">
                        <h4>Features</h4>
                        <div class="shortcut-row"><kbd>S</kbd><span>Toggle signal detection</span></div>
                        <div class="shortcut-row"><kbd>W</kbd><span>Start sweep</span></div>
                        <div class="shortcut-row"><kbd>H</kbd><span>Toggle peak hold</span></div>
                        <div class="shortcut-row"><kbd>R</kbd><span>Reset zoom</span></div>
                    </div>
                </div>
                <div class="shortcut-dismiss">Press <kbd>?</kbd> or <kbd>Esc</kbd> to close</div>
            </div>
        `;

        // Close on clicking the overlay background
        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) overlay.remove();
        });

        document.body.appendChild(overlay);
    }
}
