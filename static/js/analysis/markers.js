/**
 * Marker management for spectrum analysis.
 *
 * Supports normal markers, delta markers, and peak search.
 */

export class MarkerManager {
    constructor() {
        this._markers = [];
        this._nextId = 1;
        this._referenceMarker = null;
    }

    /**
     * Add a marker at the given frequency and power level.
     * @param {number} freq - Frequency in Hz
     * @param {number} power - Power in dB
     * @returns {Object} The created marker
     */
    addMarker(freq, power) {
        const marker = {
            id: this._nextId++,
            freq,
            power,
            isDelta: false,
        };
        this._markers.push(marker);
        return marker;
    }

    /**
     * Add a delta marker relative to the reference marker.
     */
    addDeltaMarker(freq, power) {
        if (!this._referenceMarker) {
            return this.addMarker(freq, power);
        }
        const marker = {
            id: this._nextId++,
            freq,
            power,
            isDelta: true,
            refId: this._referenceMarker.id,
            deltaFreq: freq - this._referenceMarker.freq,
            deltaPower: power - this._referenceMarker.power,
        };
        this._markers.push(marker);
        return marker;
    }

    /**
     * Remove a marker by ID.
     */
    removeMarker(id) {
        this._markers = this._markers.filter(m => m.id !== id);
        if (this._referenceMarker && this._referenceMarker.id === id) {
            this._referenceMarker = null;
        }
    }

    /**
     * Remove all markers.
     */
    clearMarkers() {
        this._markers = [];
        this._referenceMarker = null;
        this._nextId = 1;
    }

    /**
     * Set reference marker for delta measurements.
     */
    setReference(id) {
        this._referenceMarker = this._markers.find(m => m.id === id) || null;
    }

    /**
     * Find peak in spectrum data and add a marker there.
     * @param {Float32Array} spectrum
     * @param {number} centerFreq
     * @param {number} sampleRate
     * @param {number} viewStart - normalized view start (0-1)
     * @param {number} viewEnd - normalized view end (0-1)
     */
    peakSearch(spectrum, centerFreq, sampleRate, viewStart = 0, viewEnd = 1) {
        if (!spectrum || spectrum.length === 0) return null;

        const numBins = spectrum.length;
        const startBin = Math.floor(viewStart * numBins);
        const endBin = Math.ceil(viewEnd * numBins);

        let maxVal = -Infinity;
        let maxIdx = startBin;

        for (let i = startBin; i < endBin; i++) {
            if (spectrum[i] > maxVal) {
                maxVal = spectrum[i];
                maxIdx = i;
            }
        }

        const freqStart = centerFreq - sampleRate / 2;
        const freq = freqStart + (maxIdx / numBins) * sampleRate;

        return this.addMarker(freq, maxVal);
    }

    /**
     * Find next peak (excluding bins near existing markers).
     */
    nextPeakSearch(spectrum, centerFreq, sampleRate, exclusionBins = 20) {
        if (!spectrum || spectrum.length === 0) return null;

        const numBins = spectrum.length;
        const freqStart = centerFreq - sampleRate / 2;

        // Build exclusion set from existing markers
        const excluded = new Set();
        for (const marker of this._markers) {
            const bin = Math.round(((marker.freq - freqStart) / sampleRate) * numBins);
            for (let i = Math.max(0, bin - exclusionBins); i < Math.min(numBins, bin + exclusionBins); i++) {
                excluded.add(i);
            }
        }

        let maxVal = -Infinity;
        let maxIdx = -1;

        for (let i = 0; i < numBins; i++) {
            if (excluded.has(i)) continue;
            if (spectrum[i] > maxVal) {
                maxVal = spectrum[i];
                maxIdx = i;
            }
        }

        if (maxIdx === -1) return null;

        const freq = freqStart + (maxIdx / numBins) * sampleRate;
        return this.addMarker(freq, maxVal);
    }

    /**
     * Update marker power levels from current spectrum data.
     */
    updateFromSpectrum(spectrum, centerFreq, sampleRate) {
        if (!spectrum) return;
        const numBins = spectrum.length;
        const freqStart = centerFreq - sampleRate / 2;

        for (const marker of this._markers) {
            const bin = Math.round(((marker.freq - freqStart) / sampleRate) * numBins);
            if (bin >= 0 && bin < numBins) {
                marker.power = spectrum[bin];
            }

            // Update delta info
            if (marker.isDelta && this._referenceMarker) {
                marker.deltaFreq = marker.freq - this._referenceMarker.freq;
                marker.deltaPower = marker.power - this._referenceMarker.power;
            }
        }
    }

    get markers() {
        return this._markers;
    }

    get count() {
        return this._markers.length;
    }
}
