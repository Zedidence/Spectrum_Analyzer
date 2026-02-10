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
                    state.set('autoScale', !current);
                }
                break;

            case '+':
            case '=':
                e.preventDefault();
                state.set('dbRangeAdjust', 'narrow');
                break;

            case '-':
                e.preventDefault();
                state.set('dbRangeAdjust', 'widen');
                break;
        }
    }
}
