/**
 * Waterfall Display Module
 * Renders scrolling waterfall display on HTML5 Canvas
 */

class WaterfallDisplay {
    /**
     * Waterfall Display Renderer
     *
     * Renders scrolling waterfall (spectrogram) on HTML5 Canvas.
     * Uses a circular buffer to maintain history without memory reallocation.
     */

    constructor(canvasId, maxHistory = 500) {
        console.log(`Initializing WaterfallDisplay with canvas ID: ${canvasId}`);

        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            throw new Error(`Canvas element '${canvasId}' not found`);
        }

        this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
        if (!this.ctx) {
            throw new Error('Failed to get 2D context from canvas');
        }

        // Display parameters
        this.maxHistory = maxHistory;  // Maximum number of lines to store
        this.minDb = -120;  // Minimum power (blue/dark)
        this.maxDb = -20;   // Maximum power (yellow/bright)

        // Data buffer (circular buffer for memory efficiency)
        this.buffer = [];
        this.bufferIndex = 0;

        // Colormap (viridis-inspired gradient)
        console.log('Generating colormap...');
        this.colormap = this.generateColormap();
        console.log(`✓ Colormap generated: ${this.colormap.length} colors`);

        // Performance tracking
        this.linesAdded = 0;
        this.renderCount = 0;

        // Setup canvas size
        console.log('Setting up canvas...');
        this.resize();
        window.addEventListener('resize', () => this.resize());

        // Start animation loop
        console.log('Starting animation loop...');
        this.animate();
        console.log('✓ WaterfallDisplay initialized');
    }

    resize() {
        const container = this.canvas.parentElement;
        const rect = container.getBoundingClientRect();

        // Set canvas size
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';

        this.ctx.scale(dpr, dpr);

        this.width = rect.width;
        this.height = rect.height;
    }

    generateColormap() {
        // Generate a colormap array (256 colors)
        const colors = [];

        for (let i = 0; i < 256; i++) {
            const t = i / 255;

            // Viridis-inspired colormap
            let r, g, b;

            if (t < 0.25) {
                r = 68 + (t / 0.25) * (59 - 68);
                g = 1 + (t / 0.25) * (82 - 1);
                b = 84 + (t / 0.25) * (139 - 84);
            } else if (t < 0.5) {
                const t2 = (t - 0.25) / 0.25;
                r = 59 + t2 * (33 - 59);
                g = 82 + t2 * (145 - 82);
                b = 139 + t2 * (140 - 139);
            } else if (t < 0.75) {
                const t2 = (t - 0.5) / 0.25;
                r = 33 + t2 * (94 - 33);
                g = 145 + t2 * (201 - 145);
                b = 140 + t2 * (98 - 140);
            } else {
                const t2 = (t - 0.75) / 0.25;
                r = 94 + t2 * (253 - 94);
                g = 201 + t2 * (231 - 201);
                b = 98 + t2 * (37 - 98);
            }

            colors.push(`rgb(${Math.floor(r)}, ${Math.floor(g)}, ${Math.floor(b)})`);
        }

        return colors;
    }

    addLine(spectrum) {
        /**
         * Add new spectrum line to waterfall history.
         *
         * Uses circular buffer to maintain fixed-size history without
         * memory reallocation (important for performance).
         *
         * @param {Array} spectrum - Power spectrum in dB (1D array)
         */

        // Log first line
        if (this.linesAdded === 0) {
            console.log('✓ WaterfallDisplay: First line added');
            console.log(`  Bins: ${spectrum.length}`);
        }

        // Add to buffer (circular buffer)
        if (this.buffer.length < this.maxHistory) {
            // Still filling buffer
            this.buffer.push(spectrum);
        } else {
            // Buffer full - overwrite oldest
            this.buffer[this.bufferIndex] = spectrum;
            this.bufferIndex = (this.bufferIndex + 1) % this.maxHistory;
        }

        this.linesAdded++;

        // Update UI display
        const historyElem = document.getElementById('waterfall-history');
        if (historyElem) {
            historyElem.textContent = this.buffer.length;
        }

        // Log milestones
        if (this.linesAdded === this.maxHistory) {
            console.log(`✓ WaterfallDisplay: Buffer full (${this.maxHistory} lines)`);
        }
    }

    animate() {
        this.draw();
        requestAnimationFrame(() => this.animate());
    }

    draw() {
        // Clear canvas
        this.ctx.fillStyle = '#0a0e27';
        this.ctx.fillRect(0, 0, this.width, this.height);

        if (this.buffer.length === 0) {
            // Draw "Waiting for data..." message
            this.ctx.fillStyle = '#8899bb';
            this.ctx.font = '16px monospace';
            this.ctx.textAlign = 'center';
            this.ctx.fillText('Waiting for data...', this.width / 2, this.height / 2);
            return;
        }

        // Draw waterfall from buffer
        this.drawWaterfall();
    }

    drawWaterfall() {
        const numLines = this.buffer.length;
        if (numLines === 0) return;

        // Calculate line height
        const lineHeight = Math.max(1, this.height / numLines);

        // Draw from oldest to newest (top to bottom)
        for (let i = 0; i < numLines; i++) {
            // Get line from buffer (handle circular buffer)
            const bufferIdx = (this.bufferIndex + i) % numLines;
            const spectrum = this.buffer[bufferIdx];

            if (!spectrum) continue;

            const y = i * lineHeight;
            this.drawLine(spectrum, y, lineHeight);
        }
    }

    drawLine(spectrum, y, height) {
        const numBins = spectrum.length;
        const binWidth = this.width / numBins;

        for (let i = 0; i < numBins; i++) {
            const x = i * binWidth;
            const db = spectrum[i];

            // Normalize to [0, 1]
            let normalized = (db - this.minDb) / (this.maxDb - this.minDb);
            normalized = Math.max(0, Math.min(1, normalized));

            // Map to colormap index
            const colorIdx = Math.floor(normalized * 255);
            this.ctx.fillStyle = this.colormap[colorIdx];

            // Draw rectangle
            this.ctx.fillRect(x, y, Math.ceil(binWidth), Math.ceil(height));
        }
    }

    setScale(minDb, maxDb) {
        this.minDb = minDb;
        this.maxDb = maxDb;
    }

    clear() {
        this.buffer = [];
        this.bufferIndex = 0;
    }
}
