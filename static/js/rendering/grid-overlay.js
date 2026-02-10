/**
 * Grid overlay renderer (Canvas 2D).
 *
 * Draws grid lines, frequency/dB labels, and marker readouts
 * on a transparent canvas overlaid on the spectrum display.
 * Accounts for zoom/pan via viewStart/viewEnd.
 */

export class GridOverlay {
    /**
     * @param {HTMLCanvasElement} canvas - Overlay canvas (transparent, on top of spectrum)
     */
    constructor(canvas) {
        this._canvas = canvas;
        this._ctx = canvas.getContext('2d');

        this._width = 0;
        this._height = 0;

        // Display parameters
        this._dbMin = -80;
        this._dbMax = 20;
        this._centerFreq = 100e6;
        this._sampleRate = 2e6;
        this._viewStart = 0;
        this._viewEnd = 1;

        // Markers
        this._markers = [];

        // Colors
        this._gridColor = 'rgba(58, 69, 88, 0.4)';
        this._textColor = '#a0b0c0';
        this._markerColor = '#ff6b35';
        this._deltaMarkerColor = '#fbbf24';

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
     * Update display parameters.
     */
    update(params) {
        if (params.dbMin !== undefined) this._dbMin = params.dbMin;
        if (params.dbMax !== undefined) this._dbMax = params.dbMax;
        if (params.centerFreq !== undefined) this._centerFreq = params.centerFreq;
        if (params.sampleRate !== undefined) this._sampleRate = params.sampleRate;
        if (params.viewStart !== undefined) this._viewStart = params.viewStart;
        if (params.viewEnd !== undefined) this._viewEnd = params.viewEnd;
        if (params.markers !== undefined) this._markers = params.markers;
    }

    render() {
        const ctx = this._ctx;
        const w = this._width;
        const h = this._height;

        if (w === 0 || h === 0) return;

        ctx.clearRect(0, 0, w, h);

        this._drawGrid(ctx, w, h);
        this._drawDbLabels(ctx, w, h);
        this._drawFreqLabels(ctx, w, h);
        this._drawMarkers(ctx, w, h);
    }

    _drawGrid(ctx, w, h) {
        ctx.strokeStyle = this._gridColor;
        ctx.lineWidth = 0.5;

        // Horizontal grid lines (dB)
        const dbRange = this._dbMax - this._dbMin;
        const dbStep = this._calcDbStep(dbRange);
        const dbStart = Math.ceil(this._dbMin / dbStep) * dbStep;
        for (let db = dbStart; db <= this._dbMax; db += dbStep) {
            const y = h - ((db - this._dbMin) / dbRange) * h;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
            ctx.stroke();
        }

        // Vertical grid lines (frequency)
        const viewSpan = this._viewEnd - this._viewStart;
        const freqStart = this._centerFreq - this._sampleRate / 2;
        const viewFreqStart = freqStart + this._viewStart * this._sampleRate;
        const viewFreqSpan = viewSpan * this._sampleRate;
        const freqStep = this._calcFreqStep(viewFreqSpan);
        const firstFreq = Math.ceil(viewFreqStart / freqStep) * freqStep;

        for (let freq = firstFreq; freq < viewFreqStart + viewFreqSpan; freq += freqStep) {
            const normInView = (freq - viewFreqStart) / viewFreqSpan;
            const x = normInView * w;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, h);
            ctx.stroke();
        }
    }

    _drawDbLabels(ctx, w, h) {
        ctx.fillStyle = this._textColor;
        ctx.font = '11px monospace';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';

        const dbRange = this._dbMax - this._dbMin;
        const dbStep = this._calcDbStep(dbRange);
        const dbStart = Math.ceil(this._dbMin / dbStep) * dbStep;

        for (let db = dbStart; db <= this._dbMax; db += dbStep) {
            const y = h - ((db - this._dbMin) / dbRange) * h;
            ctx.fillText(db.toFixed(0) + ' dB', 4, y);
        }
    }

    _drawFreqLabels(ctx, w, h) {
        ctx.fillStyle = this._textColor;
        ctx.font = '11px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';

        const viewSpan = this._viewEnd - this._viewStart;
        const freqStart = this._centerFreq - this._sampleRate / 2;
        const viewFreqStart = freqStart + this._viewStart * this._sampleRate;
        const viewFreqSpan = viewSpan * this._sampleRate;
        const freqStep = this._calcFreqStep(viewFreqSpan);
        const firstFreq = Math.ceil(viewFreqStart / freqStep) * freqStep;

        for (let freq = firstFreq; freq < viewFreqStart + viewFreqSpan; freq += freqStep) {
            const normInView = (freq - viewFreqStart) / viewFreqSpan;
            const x = normInView * w;
            ctx.fillText(this._formatFreq(freq), x, h - 2);
        }
    }

    _drawMarkers(ctx, w, h) {
        const dbRange = this._dbMax - this._dbMin;
        const viewSpan = this._viewEnd - this._viewStart;
        const freqStart = this._centerFreq - this._sampleRate / 2;
        const viewFreqStart = freqStart + this._viewStart * this._sampleRate;
        const viewFreqSpan = viewSpan * this._sampleRate;

        for (const marker of this._markers) {
            const normInView = (marker.freq - viewFreqStart) / viewFreqSpan;
            if (normInView < 0 || normInView > 1) continue;

            const x = normInView * w;
            const yNorm = (marker.power - this._dbMin) / dbRange;
            const y = h - Math.max(0, Math.min(1, yNorm)) * h;

            const color = marker.isDelta ? this._deltaMarkerColor : this._markerColor;

            // Vertical line
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, h);
            ctx.stroke();
            ctx.setLineDash([]);

            // Diamond marker at signal level
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(x, y - 6);
            ctx.lineTo(x + 5, y);
            ctx.lineTo(x, y + 6);
            ctx.lineTo(x - 5, y);
            ctx.closePath();
            ctx.fill();

            // Label
            ctx.fillStyle = color;
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'bottom';
            const labelX = Math.min(x + 8, w - 120);
            const labelY = Math.max(y - 4, 24);

            // Background for readability
            const label1 = `M${marker.id}: ${this._formatFreq(marker.freq)}`;
            const label2 = `${marker.power.toFixed(1)} dB`;
            const textWidth = Math.max(
                ctx.measureText(label1).width,
                ctx.measureText(label2).width,
            );
            ctx.fillStyle = 'rgba(10, 14, 39, 0.85)';
            ctx.fillRect(labelX - 2, labelY - 24, textWidth + 6, 26);

            ctx.fillStyle = color;
            ctx.fillText(label1, labelX, labelY - 12);
            ctx.fillText(label2, labelX, labelY);
        }
    }

    _calcDbStep(range) {
        if (range <= 30) return 5;
        if (range <= 60) return 10;
        return 20;
    }

    _calcFreqStep(spanHz) {
        const target = spanHz / 8; // Aim for ~8 labels
        const magnitudes = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
        const scale = Math.pow(10, Math.floor(Math.log10(target)));

        for (const m of magnitudes) {
            const step = m * scale;
            if (step >= target * 0.5) return step;
        }
        return target;
    }

    _formatFreq(freqHz) {
        if (freqHz >= 1e9) return (freqHz / 1e9).toFixed(4) + ' GHz';
        if (freqHz >= 1e6) return (freqHz / 1e6).toFixed(3) + ' MHz';
        if (freqHz >= 1e3) return (freqHz / 1e3).toFixed(1) + ' kHz';
        return freqHz.toFixed(0) + ' Hz';
    }

    setDbRange(min, max) {
        this._dbMin = min;
        this._dbMax = max;
    }
}
