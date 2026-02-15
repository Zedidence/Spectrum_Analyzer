/**
 * Panoramic spectrum renderer for sweep mode.
 *
 * Renders a wideband stitched spectrum with absolute frequency axis.
 * Supports zoom/pan, sweep progress visualization, and auto-scaling.
 * Follows the same pattern as SpectrumRenderer but operates on
 * absolute frequency ranges rather than normalized bin positions.
 */

export class PanoramaRenderer {
    /**
     * @param {HTMLCanvasElement} canvas
     * @param {HTMLCanvasElement} overlayCanvas
     */
    constructor(canvas, overlayCanvas) {
        this._canvas = canvas;
        this._ctx = canvas.getContext('2d');
        this._overlay = overlayCanvas;
        this._overlayCtx = overlayCanvas.getContext('2d');

        // Display parameters
        this._dbMin = -120;
        this._dbMax = -20;

        // Frequency range (Hz)
        this._freqStart = 47e6;
        this._freqEnd = 6e9;

        // Zoom view (normalized 0-1 over the sweep range)
        this._viewStart = 0;
        this._viewEnd = 1;

        // Auto-scale
        this._autoScale = true;
        this._targetDbMin = -120;
        this._targetDbMax = -20;
        this._autoScaleFrames = 0;

        // Spectrum data
        this._spectrum = null;
        this._numBins = 0;

        // Sweep progress
        this._sweepProgress = 0;  // 0-1
        this._sweepMode = 'off';
        this._sweepTimeMs = 0;
        this._sweepComplete = false;

        // Segment tracking for incremental rendering
        this._segments = new Map();  // step_idx -> Float32Array
        this._totalSegments = 0;
        this._completedSegments = 0;

        // Colors
        this._bgColor = '#0a0e27';
        this._traceColor = '#00ff88';  // Green for panorama (vs cyan for live)
        this._fillGradientTop = 'rgba(0, 255, 136, 0.15)';
        this._fillGradientBot = 'rgba(0, 255, 136, 0.02)';
        this._unscanColor = 'rgba(255, 255, 255, 0.03)';
        this._gridColor = 'rgba(255, 255, 255, 0.08)';
        this._labelColor = 'rgba(200, 210, 220, 0.7)';
        this._progressColor = '#fbbf24';

        // Sizing
        this._width = 0;
        this._height = 0;

        // Mouse interaction
        this._isDragging = false;
        this._dragStartX = 0;
        this._dragStartView = 0;

        this._initResize();
        this._initInteraction();
    }

    _initResize() {
        const observer = new ResizeObserver(entries => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect;
                if (width === 0 || height === 0) return;

                const dpr = window.devicePixelRatio || 1;

                // Main canvas
                this._canvas.width = Math.floor(width * dpr);
                this._canvas.height = Math.floor(height * dpr);
                this._canvas.style.width = width + 'px';
                this._canvas.style.height = height + 'px';
                this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

                // Overlay canvas
                this._overlay.width = Math.floor(width * dpr);
                this._overlay.height = Math.floor(height * dpr);
                this._overlay.style.width = width + 'px';
                this._overlay.style.height = height + 'px';
                this._overlayCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

                this._width = width;
                this._height = height;
            }
        });
        observer.observe(this._canvas.parentElement);
    }

    _initInteraction() {
        const el = this._canvas.parentElement;

        // Mouse wheel zoom
        el.addEventListener('wheel', (e) => {
            e.preventDefault();
            const rect = el.getBoundingClientRect();
            const mouseX = (e.clientX - rect.left) / rect.width;
            const viewPos = this._viewStart + mouseX * (this._viewEnd - this._viewStart);

            const factor = e.deltaY < 0 ? 0.87 : 1.15;
            const span = (this._viewEnd - this._viewStart) * factor;
            const clampedSpan = Math.max(0.01, Math.min(1.0, span));

            this._viewStart = Math.max(0, viewPos - mouseX * clampedSpan);
            this._viewEnd = Math.min(1, this._viewStart + clampedSpan);
            if (this._viewEnd > 1) {
                this._viewEnd = 1;
                this._viewStart = Math.max(0, 1 - clampedSpan);
            }
        }, { passive: false });

        // Click-drag pan
        el.addEventListener('mousedown', (e) => {
            this._isDragging = true;
            this._dragStartX = e.clientX;
            this._dragStartView = this._viewStart;
        });

        window.addEventListener('mousemove', (e) => {
            if (!this._isDragging) return;
            const rect = el.getBoundingClientRect();
            const dx = (e.clientX - this._dragStartX) / rect.width;
            const span = this._viewEnd - this._viewStart;
            let newStart = this._dragStartView - dx * span;
            newStart = Math.max(0, Math.min(1 - span, newStart));
            this._viewStart = newStart;
            this._viewEnd = newStart + span;
        });

        window.addEventListener('mouseup', () => {
            this._isDragging = false;
        });

        // Double-click reset
        el.addEventListener('dblclick', () => {
            this._viewStart = 0;
            this._viewEnd = 1;
        });
    }

    /**
     * Update with a complete panorama from the server.
     */
    updatePanorama(data) {
        this._spectrum = data.spectrum;
        this._numBins = data.spectrum.length;
        this._freqStart = data.freqStart;
        this._freqEnd = data.freqEnd;
        this._sweepTimeMs = data.sweepTimeMs;
        this._sweepComplete = true;
        this._sweepMode = data.sweepMode === 0 ? 'survey' : 'band_monitor';

        if (this._autoScale && this._spectrum) {
            this._updateAutoScale();
        }
    }

    /**
     * Update with an incremental sweep segment.
     */
    updateSegment(data) {
        this._totalSegments = data.totalSegments;
        this._segments.set(data.segmentIdx, data.spectrum);
        this._completedSegments = this._segments.size;
        this._sweepProgress = this._completedSegments / this._totalSegments;
        this._freqStart = data.sweepStart;
        this._freqEnd = data.sweepEnd;
        this._sweepComplete = false;
        this._sweepMode = 'survey';

        // Build composite spectrum from segments for rendering
        this._buildFromSegments();

        if (this._autoScale && this._spectrum) {
            this._updateAutoScale();
        }
    }

    /**
     * Assemble partial spectrum from collected segments.
     */
    _buildFromSegments() {
        if (this._totalSegments === 0) return;

        // Estimate segment size from first available segment
        const firstSeg = this._segments.values().next().value;
        if (!firstSeg) return;
        const segSize = firstSeg.length;

        // Allocate for ALL segments (including gaps) to prevent out-of-bounds
        const totalBins = this._totalSegments * segSize;
        this._spectrum = new Float32Array(totalBins);
        this._spectrum.fill(-200);
        this._numBins = totalBins;

        for (let i = 0; i < this._totalSegments; i++) {
            const seg = this._segments.get(i);
            if (seg) {
                const offset = i * segSize;
                this._spectrum.set(seg, offset);
            }
        }
    }

    _updateAutoScale() {
        const spectrum = this._spectrum;
        if (!spectrum) return;

        const viewStartBin = Math.floor(this._viewStart * this._numBins);
        const viewEndBin = Math.ceil(this._viewEnd * this._numBins);

        let visMin = Infinity;
        let visMax = -Infinity;
        for (let i = viewStartBin; i < viewEndBin && i < this._numBins; i++) {
            if (spectrum[i] > -190) {  // Skip unscanned bins
                if (spectrum[i] < visMin) visMin = spectrum[i];
                if (spectrum[i] > visMax) visMax = spectrum[i];
            }
        }

        if (visMin === Infinity) return;

        const margin = 10;
        this._targetDbMin = Math.floor((visMin - margin) / 10) * 10;
        this._targetDbMax = Math.ceil((visMax + margin) / 10) * 10;

        if (this._targetDbMax - this._targetDbMin < 40) {
            const center = (this._targetDbMax + this._targetDbMin) / 2;
            this._targetDbMin = center - 20;
            this._targetDbMax = center + 20;
        }

        this._autoScaleFrames++;
        const a = this._autoScaleFrames <= 3 ? 0.5 : 0.08;
        this._dbMin += a * (this._targetDbMin - this._dbMin);
        this._dbMax += a * (this._targetDbMax - this._dbMax);
    }

    /** Full render pass. */
    render() {
        this._renderSpectrum();
        this._renderOverlay();
    }

    _renderSpectrum() {
        const ctx = this._ctx;
        const w = this._width;
        const h = this._height;
        if (w === 0 || h === 0) return;

        // Clear
        ctx.fillStyle = this._bgColor;
        ctx.fillRect(0, 0, w, h);

        if (!this._spectrum || this._numBins === 0) {
            // Draw "waiting" message
            ctx.fillStyle = this._labelColor;
            ctx.font = '14px monospace';
            ctx.textAlign = 'center';
            ctx.fillText('Start a sweep to see panoramic spectrum', w / 2, h / 2);
            ctx.textAlign = 'left';
            return;
        }

        // Draw filled area
        this._drawFill(ctx, w, h);

        // Draw trace
        this._drawTrace(ctx, w, h);

        // Draw progress indicator for in-progress sweeps
        if (!this._sweepComplete && this._sweepProgress > 0) {
            // Map progress through the current zoom/pan view transform
            const viewSpan = this._viewEnd - this._viewStart;
            const progressX = ((this._sweepProgress - this._viewStart) / viewSpan) * w;
            if (progressX >= 0 && progressX <= w) {
                ctx.strokeStyle = this._progressColor;
                ctx.lineWidth = 2;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(progressX, 0);
                ctx.lineTo(progressX, h);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }
    }

    _drawTrace(ctx, w, h) {
        const spectrum = this._spectrum;
        const numBins = this._numBins;
        const dbRange = this._dbMax - this._dbMin;
        const viewSpan = this._viewEnd - this._viewStart;

        const startBin = Math.max(0, Math.floor(this._viewStart * numBins) - 1);
        const endBin = Math.min(numBins, Math.ceil(this._viewEnd * numBins) + 1);

        ctx.strokeStyle = this._traceColor;
        ctx.lineWidth = 1.5;
        ctx.beginPath();

        let first = true;
        for (let i = startBin; i < endBin; i++) {
            if (spectrum[i] < -190) continue;  // Skip unscanned

            const binNorm = i / numBins;
            const x = ((binNorm - this._viewStart) / viewSpan) * w;
            let normalized = (spectrum[i] - this._dbMin) / dbRange;
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
    }

    _drawFill(ctx, w, h) {
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

        const firstX = ((startBin / numBins - this._viewStart) / viewSpan) * w;
        ctx.moveTo(firstX, h);

        for (let i = startBin; i < endBin; i++) {
            const binNorm = i / numBins;
            const x = ((binNorm - this._viewStart) / viewSpan) * w;

            if (spectrum[i] < -190) {
                ctx.lineTo(x, h);
                continue;
            }

            let normalized = (spectrum[i] - this._dbMin) / dbRange;
            normalized = Math.max(0, Math.min(1, normalized));
            ctx.lineTo(x, h - normalized * h);
        }

        const lastX = (((endBin - 1) / numBins - this._viewStart) / viewSpan) * w;
        ctx.lineTo(lastX, h);
        ctx.closePath();
        ctx.fill();
    }

    _renderOverlay() {
        const ctx = this._overlayCtx;
        const w = this._width;
        const h = this._height;
        if (w === 0 || h === 0) return;

        ctx.clearRect(0, 0, w, h);

        this._drawGrid(ctx, w, h);
        this._drawInfo(ctx, w, h);
    }

    _drawGrid(ctx, w, h) {
        const dbRange = this._dbMax - this._dbMin;
        const viewSpan = this._viewEnd - this._viewStart;
        const viewFreqStart = this._freqStart + this._viewStart * (this._freqEnd - this._freqStart);
        const viewFreqEnd = this._freqStart + this._viewEnd * (this._freqEnd - this._freqStart);
        const viewFreqSpan = viewFreqEnd - viewFreqStart;

        // Horizontal grid lines (dB)
        const dbStep = this._calcStep(dbRange, h, 60);
        ctx.strokeStyle = this._gridColor;
        ctx.lineWidth = 1;
        ctx.fillStyle = this._labelColor;
        ctx.font = '10px monospace';

        const dbStart = Math.ceil(this._dbMin / dbStep) * dbStep;
        for (let db = dbStart; db <= this._dbMax; db += dbStep) {
            const y = h - ((db - this._dbMin) / dbRange) * h;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
            ctx.stroke();
            ctx.fillText(`${db.toFixed(0)} dB`, 4, y - 2);
        }

        // Vertical grid lines (frequency)
        const freqStep = this._calcFreqStep(viewFreqSpan, w);
        const freqGridStart = Math.ceil(viewFreqStart / freqStep) * freqStep;
        for (let f = freqGridStart; f <= viewFreqEnd; f += freqStep) {
            const normPos = (f - this._freqStart) / (this._freqEnd - this._freqStart);
            const x = ((normPos - this._viewStart) / viewSpan) * w;

            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, h);
            ctx.stroke();

            ctx.fillText(this._formatFreq(f), x + 3, h - 4);
        }
    }

    _drawInfo(ctx, w, h) {
        ctx.fillStyle = this._labelColor;
        ctx.font = '11px monospace';

        // Top-left: sweep info
        const modeLabel = this._sweepMode === 'band_monitor' ? 'BAND MONITOR' : 'SURVEY';
        ctx.fillText(modeLabel, 4, 14);

        if (this._sweepComplete && this._sweepTimeMs > 0) {
            ctx.fillText(`Sweep: ${this._sweepTimeMs.toFixed(0)} ms`, 4, 28);
        } else if (this._sweepProgress > 0) {
            ctx.fillText(`Progress: ${(this._sweepProgress * 100).toFixed(0)}%`, 4, 28);
        }

        // Top-right: frequency range
        const viewFreqStart = this._freqStart + this._viewStart * (this._freqEnd - this._freqStart);
        const viewFreqEnd = this._freqStart + this._viewEnd * (this._freqEnd - this._freqStart);
        const rangeText = `${this._formatFreq(viewFreqStart)} - ${this._formatFreq(viewFreqEnd)}`;
        ctx.textAlign = 'right';
        ctx.fillText(rangeText, w - 4, 14);

        if (this._viewStart > 0.001 || this._viewEnd < 0.999) {
            const pct = ((this._viewEnd - this._viewStart) * 100).toFixed(1);
            ctx.fillText(`Zoom: ${pct}%`, w - 4, 28);
        }
        ctx.textAlign = 'left';
    }

    _calcStep(range, pixels, targetSpacing) {
        const rough = range * targetSpacing / pixels;
        const steps = [1, 2, 5, 10, 20, 50, 100];
        for (const s of steps) {
            if (s >= rough) return s;
        }
        return 100;
    }

    _calcFreqStep(freqSpan, pixels) {
        const targetLabels = Math.max(4, Math.floor(pixels / 120));
        const rough = freqSpan / targetLabels;

        const steps = [
            1e3, 2e3, 5e3, 10e3, 20e3, 50e3, 100e3, 200e3, 500e3,
            1e6, 2e6, 5e6, 10e6, 20e6, 50e6, 100e6, 200e6, 500e6, 1e9,
        ];
        for (const s of steps) {
            if (s >= rough) return s;
        }
        return 1e9;
    }

    _formatFreq(hz) {
        if (hz >= 1e9) return (hz / 1e9).toFixed(2) + ' GHz';
        if (hz >= 1e6) return (hz / 1e6).toFixed(1) + ' MHz';
        if (hz >= 1e3) return (hz / 1e3).toFixed(0) + ' kHz';
        return hz.toFixed(0) + ' Hz';
    }

    /** Reset for a new sweep. */
    resetSweep() {
        this._spectrum = null;
        this._numBins = 0;
        this._segments.clear();
        this._totalSegments = 0;
        this._completedSegments = 0;
        this._sweepProgress = 0;
        this._sweepComplete = false;
        this._autoScaleFrames = 0;
    }

    get dbMin() { return this._dbMin; }
    get dbMax() { return this._dbMax; }

    setAutoScale(enabled) {
        this._autoScale = enabled;
        if (enabled) this._autoScaleFrames = 0;
    }
}
