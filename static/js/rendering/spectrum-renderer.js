/**
 * Spectrum display renderer (Canvas 2D with zoom support).
 *
 * Draws the power spectrum as a line graph with peak hold trace.
 * Grid and labels are handled by GridOverlay (separate canvas layer).
 * Zoom/pan support via viewStart/viewEnd parameters.
 */

export class SpectrumRenderer {
    /**
     * @param {HTMLCanvasElement} canvas
     */
    constructor(canvas) {
        this._canvas = canvas;
        this._ctx = canvas.getContext('2d');

        // Display parameters
        this._dbMin = -80;
        this._dbMax = 20;
        this._centerFreq = 100e6;
        this._sampleRate = 2e6;

        // Zoom view (normalized 0-1)
        this._viewStart = 0;
        this._viewEnd = 1;

        // Auto-scale state
        this._autoScale = false;
        this._targetDbMin = -80;
        this._targetDbMax = 20;
        this._autoScaleAlpha = 0.05;

        // Data
        this._spectrum = null;
        this._peakHold = null;
        this._numBins = 0;

        // Colors
        this._bgColor = '#0a0e27';
        this._traceColor = '#00d9ff';
        this._peakHoldColor = '#ff6b35';
        this._fillGradientTop = 'rgba(0, 217, 255, 0.15)';
        this._fillGradientBot = 'rgba(0, 217, 255, 0.02)';

        // Sizing
        this._width = 0;
        this._height = 0;

        // Peak cache
        this._peakIdx = -1;
        this._peakPower = -200;
        this._peakFreq = 0;

        this._initResize();
    }

    _initResize() {
        const observer = new ResizeObserver(entries => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect;
                if (width === 0 || height === 0) return;

                const dpr = window.devicePixelRatio || 1;
                this._canvas.width = Math.floor(width * dpr);
                this._canvas.height = Math.floor(height * dpr);
                this._canvas.style.width = width + 'px';
                this._canvas.style.height = height + 'px';
                this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                this._width = width;
                this._height = height;
            }
        });
        observer.observe(this._canvas.parentElement);
    }

    /**
     * Set zoom view range.
     * @param {number} start - 0 to 1
     * @param {number} end - 0 to 1
     */
    setView(start, end) {
        this._viewStart = start;
        this._viewEnd = end;
    }

    /**
     * Update spectrum data.
     * @param {Float32Array} spectrum
     * @param {number} centerFreq
     * @param {number} sampleRate
     * @param {Float32Array|null} peakHold
     */
    updateData(spectrum, centerFreq, sampleRate, peakHold = null) {
        this._spectrum = spectrum;
        this._peakHold = peakHold;
        this._numBins = spectrum.length;
        this._centerFreq = centerFreq;
        this._sampleRate = sampleRate;

        // Update peak (within current view)
        const startBin = Math.floor(this._viewStart * this._numBins);
        const endBin = Math.ceil(this._viewEnd * this._numBins);
        let maxVal = -Infinity;
        let maxIdx = startBin;
        for (let i = startBin; i < endBin; i++) {
            if (spectrum[i] > maxVal) {
                maxVal = spectrum[i];
                maxIdx = i;
            }
        }
        this._peakIdx = maxIdx;
        this._peakPower = maxVal;
        this._peakFreq = centerFreq - sampleRate / 2 +
            (maxIdx / this._numBins) * sampleRate;

        // Auto-scale dB range
        if (this._autoScale) {
            this._updateAutoScale(spectrum, startBin, endBin);
        }
    }

    _updateAutoScale(spectrum, startBin, endBin) {
        // Find min/max in visible region
        let visMin = Infinity;
        let visMax = -Infinity;
        for (let i = startBin; i < endBin; i++) {
            if (spectrum[i] < visMin) visMin = spectrum[i];
            if (spectrum[i] > visMax) visMax = spectrum[i];
        }

        // Add margins and snap to 10 dB grid
        const margin = 10;
        this._targetDbMin = Math.floor((visMin - margin) / 10) * 10;
        this._targetDbMax = Math.ceil((visMax + margin) / 10) * 10;

        // Ensure minimum range
        if (this._targetDbMax - this._targetDbMin < 30) {
            this._targetDbMax = this._targetDbMin + 30;
        }

        // Smooth approach
        const a = this._autoScaleAlpha;
        this._dbMin += a * (this._targetDbMin - this._dbMin);
        this._dbMax += a * (this._targetDbMax - this._dbMax);
    }

    /** Render the spectrum display. */
    render() {
        const ctx = this._ctx;
        const w = this._width;
        const h = this._height;

        if (w === 0 || h === 0) return;

        // Clear
        ctx.fillStyle = this._bgColor;
        ctx.fillRect(0, 0, w, h);

        // Peak hold trace (draw first so spectrum trace is on top)
        if (this._peakHold) {
            this._drawDataTrace(ctx, w, h, this._peakHold, this._peakHoldColor, 1, [4, 4]);
        }

        // Spectrum trace with fill
        if (this._spectrum) {
            this._drawSpectrumFill(ctx, w, h);
            this._drawDataTrace(ctx, w, h, this._spectrum, this._traceColor, 1.5, []);
        }
    }

    /**
     * Draw a data trace (spectrum or peak hold) accounting for zoom.
     */
    _drawDataTrace(ctx, w, h, data, color, lineWidth, lineDash) {
        const numBins = data.length;
        const dbRange = this._dbMax - this._dbMin;
        const viewSpan = this._viewEnd - this._viewStart;

        // Determine visible bin range
        const startBin = Math.max(0, Math.floor(this._viewStart * numBins) - 1);
        const endBin = Math.min(numBins, Math.ceil(this._viewEnd * numBins) + 1);

        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        if (lineDash.length > 0) ctx.setLineDash(lineDash);
        ctx.beginPath();

        let first = true;
        for (let i = startBin; i < endBin; i++) {
            // Map bin position to screen x (accounting for zoom)
            const binNorm = i / numBins;
            const x = ((binNorm - this._viewStart) / viewSpan) * w;

            let normalized = (data[i] - this._dbMin) / dbRange;
            normalized = Math.max(0, Math.min(1, normalized));
            const y = h - normalized * h;

            if (first) {
                ctx.moveTo(x, y);
                first = false;
            } else {
                ctx.lineTo(x, y);
            }
        }
        ctx.stroke();
        if (lineDash.length > 0) ctx.setLineDash([]);
    }

    /**
     * Draw filled area under spectrum trace.
     */
    _drawSpectrumFill(ctx, w, h) {
        const spectrum = this._spectrum;
        const numBins = this._numBins;
        const dbRange = this._dbMax - this._dbMin;
        const viewSpan = this._viewEnd - this._viewStart;

        const startBin = Math.max(0, Math.floor(this._viewStart * numBins) - 1);
        const endBin = Math.min(numBins, Math.ceil(this._viewEnd * numBins) + 1);

        const gradient = ctx.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, this._fillGradientTop);
        gradient.addColorStop(1, this._fillGradientBot);

        ctx.fillStyle = gradient;
        ctx.beginPath();

        // Start at bottom-left of visible area
        const firstX = ((startBin / numBins - this._viewStart) / viewSpan) * w;
        ctx.moveTo(firstX, h);

        for (let i = startBin; i < endBin; i++) {
            const binNorm = i / numBins;
            const x = ((binNorm - this._viewStart) / viewSpan) * w;
            let normalized = (spectrum[i] - this._dbMin) / dbRange;
            normalized = Math.max(0, Math.min(1, normalized));
            const y = h - normalized * h;
            ctx.lineTo(x, y);
        }

        // Close path at bottom-right
        const lastX = (((endBin - 1) / numBins - this._viewStart) / viewSpan) * w;
        ctx.lineTo(lastX, h);
        ctx.closePath();
        ctx.fill();
    }

    /** Set dB display range. */
    setDbRange(min, max) {
        this._dbMin = min;
        this._dbMax = max;
    }

    /** Enable/disable auto-scale. */
    setAutoScale(enabled) {
        this._autoScale = enabled;
    }

    get dbMin() { return this._dbMin; }
    get dbMax() { return this._dbMax; }
    get autoScale() { return this._autoScale; }

    /** Get peak info for UI display. */
    getPeakInfo() {
        return {
            freq: this._peakFreq,
            power: this._peakPower,
        };
    }

    /** Get current spectrum data. */
    getSpectrum() {
        return this._spectrum;
    }
}
