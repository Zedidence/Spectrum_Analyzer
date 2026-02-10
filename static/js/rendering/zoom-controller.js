/**
 * Zoom and pan controller for spectrum display.
 *
 * Mouse wheel zooms centered on cursor, click-drag pans, double-click resets.
 * Manages a view window [freqStart, freqEnd] within the full span.
 */

export class ZoomController {
    /**
     * @param {HTMLElement} target - Element to attach mouse events to
     */
    constructor(target) {
        this._target = target;

        // View state (normalized: 0 = start of span, 1 = end of span)
        this._viewStart = 0;
        this._viewEnd = 1;

        // Zoom limits
        this._minSpan = 0.01;  // Minimum 1% of total span
        this._maxSpan = 1.0;

        // Pan state
        this._dragging = false;
        this._dragStartX = 0;
        this._dragStartViewStart = 0;
        this._dragStartViewEnd = 0;

        // Cursor position (normalized 0-1 within target)
        this._cursorX = 0.5;

        // Change callback
        this._onChange = null;

        this._initEvents();
    }

    _initEvents() {
        const el = this._target;

        // Mouse wheel zoom
        el.addEventListener('wheel', (e) => {
            e.preventDefault();
            const rect = el.getBoundingClientRect();
            this._cursorX = (e.clientX - rect.left) / rect.width;

            const zoomFactor = e.deltaY > 0 ? 1.15 : 0.87;
            this._zoom(zoomFactor, this._cursorX);
        }, { passive: false });

        // Click-drag pan
        el.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return; // Left click only
            this._dragging = true;
            this._dragStartX = e.clientX;
            this._dragStartViewStart = this._viewStart;
            this._dragStartViewEnd = this._viewEnd;
            el.style.cursor = 'grabbing';
        });

        document.addEventListener('mousemove', (e) => {
            if (!this._dragging) return;
            const rect = el.getBoundingClientRect();
            const deltaX = (e.clientX - this._dragStartX) / rect.width;
            this._pan(-deltaX);
        });

        document.addEventListener('mouseup', () => {
            if (this._dragging) {
                this._dragging = false;
                el.style.cursor = '';
            }
        });

        // Double-click reset
        el.addEventListener('dblclick', () => {
            this.reset();
        });

        // Track cursor for hover info
        el.addEventListener('mousemove', (e) => {
            if (this._dragging) return;
            const rect = el.getBoundingClientRect();
            this._cursorX = (e.clientX - rect.left) / rect.width;
        });
    }

    _zoom(factor, centerNorm) {
        const span = this._viewEnd - this._viewStart;
        const newSpan = Math.max(this._minSpan, Math.min(this._maxSpan, span * factor));

        if (newSpan === span) return;

        // Zoom centered on cursor position within the view
        const viewCursor = this._viewStart + centerNorm * span;
        const newStart = viewCursor - centerNorm * newSpan;
        const newEnd = viewCursor + (1 - centerNorm) * newSpan;

        this._setView(newStart, newEnd);
    }

    _pan(deltaNorm) {
        const span = this._dragStartViewEnd - this._dragStartViewStart;
        const delta = deltaNorm * span;
        this._setView(
            this._dragStartViewStart + delta,
            this._dragStartViewEnd + delta,
        );
    }

    _setView(start, end) {
        const span = end - start;

        // Clamp to [0, 1]
        if (start < 0) {
            start = 0;
            end = span;
        }
        if (end > 1) {
            end = 1;
            start = 1 - span;
        }

        this._viewStart = Math.max(0, start);
        this._viewEnd = Math.min(1, end);

        if (this._onChange) {
            this._onChange(this._viewStart, this._viewEnd);
        }
    }

    reset() {
        this._viewStart = 0;
        this._viewEnd = 1;
        if (this._onChange) {
            this._onChange(0, 1);
        }
    }

    /** Register change callback. */
    onChange(fn) {
        this._onChange = fn;
    }

    get viewStart() { return this._viewStart; }
    get viewEnd() { return this._viewEnd; }
    get isZoomed() { return this._viewStart > 0.001 || this._viewEnd < 0.999; }
    get cursorX() { return this._cursorX; }

    /**
     * Convert a cursor position within the element to a normalized frequency position
     * within the full span (accounting for zoom).
     */
    cursorToFreqNorm(cursorNorm) {
        return this._viewStart + cursorNorm * (this._viewEnd - this._viewStart);
    }
}
