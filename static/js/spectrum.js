/**
 * Spectrum Display Module
 * Renders real-time power spectrum on HTML5 Canvas
 */

class SpectrumDisplay {
    /**
     * Spectrum Display Renderer
     *
     * Renders real-time power spectrum on HTML5 Canvas using 2D context.
     * Uses requestAnimationFrame for smooth 60 FPS rendering.
     */

    constructor(canvasId) {
        console.log(`Initializing SpectrumDisplay with canvas ID: ${canvasId}`);

        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            throw new Error(`Canvas element '${canvasId}' not found`);
        }

        this.ctx = this.canvas.getContext('2d');
        if (!this.ctx) {
            throw new Error('Failed to get 2D context from canvas');
        }

        // Display parameters
        this.minDb = -120;  // Minimum power (dB) - adjust for noise floor
        this.maxDb = -20;   // Maximum power (dB) - adjust for signal peaks
        this.gridLines = 10;

        // Data
        this.spectrum = null;
        this.centerFreq = 100e6;  // Hz (default FM radio)
        this.sampleRate = 2.4e6;  // Hz

        // Colors
        this.backgroundColor = '#0a0e27';
        this.gridColor = '#1a2332';
        this.textColor = '#8899bb';
        this.spectrumColor = '#00ffff';  // Cyan for good visibility

        // Performance tracking
        this.renderCount = 0;
        this.lastDataUpdate = Date.now();

        // Setup canvas size
        console.log('Setting up canvas...');
        this.resize();
        window.addEventListener('resize', () => this.resize());

        // Start animation loop
        console.log('Starting animation loop...');
        this.animate();
        console.log('✓ SpectrumDisplay initialized');
    }

    resize() {
        // Get parent container size
        const container = this.canvas.parentElement;
        const rect = container.getBoundingClientRect();

        // Set canvas size (account for high DPI displays)
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';

        // Scale context to match DPI
        this.ctx.scale(dpr, dpr);

        // Store logical size
        this.width = rect.width;
        this.height = rect.height;
    }

    updateData(spectrum, centerFreq, sampleRate) {
        /**
         * Update spectrum data.
         *
         * Called by main app when new FFT data arrives from backend.
         * Data is stored and will be rendered on next animation frame.
         */

        // Log first update
        if (!this.spectrum) {
            console.log('✓ SpectrumDisplay: First data received');
            console.log(`  Bins: ${spectrum.length}, Freq: ${(centerFreq/1e6).toFixed(1)} MHz`);
        }

        this.spectrum = spectrum;
        this.centerFreq = centerFreq;
        this.sampleRate = sampleRate;
        this.lastDataUpdate = Date.now();
    }

    animate() {
        /**
         * Animation loop using requestAnimationFrame.
         *
         * This provides smooth 60 FPS rendering regardless of data update rate.
         */
        this.draw();
        requestAnimationFrame(() => this.animate());
    }

    draw() {
        /**
         * Main rendering function.
         *
         * Draws background, grid, axes, and spectrum trace.
         */

        this.renderCount++;

        // Clear canvas with background color
        this.ctx.fillStyle = this.backgroundColor;
        this.ctx.fillRect(0, 0, this.width, this.height);

        if (!this.spectrum || this.spectrum.length === 0) {
            // Draw "Waiting for data..." message
            this.ctx.fillStyle = this.textColor;
            this.ctx.font = '16px monospace';
            this.ctx.textAlign = 'center';
            this.ctx.fillText('Waiting for data...', this.width / 2, this.height / 2);

            // Log periodically if waiting too long
            if (this.renderCount % 60 === 0) {
                const waitTime = (Date.now() - this.lastDataUpdate) / 1000;
                console.log(`⚠ SpectrumDisplay: Still waiting for data (${waitTime.toFixed(1)}s)`);
            }

            return;
        }

        // Draw visualization
        this.drawGrid();
        this.drawAxes();
        this.drawSpectrum();

        // Log rendering stats occasionally
        if (this.renderCount % 600 === 0) {  // Every 10 seconds at 60 FPS
            console.log(`SpectrumDisplay: ${this.renderCount} frames rendered`);
        }
    }

    drawGrid() {
        this.ctx.strokeStyle = this.gridColor;
        this.ctx.lineWidth = 1;

        // Horizontal grid lines
        for (let i = 0; i <= this.gridLines; i++) {
            const y = (i / this.gridLines) * this.height;
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(this.width, y);
            this.ctx.stroke();
        }

        // Vertical grid lines
        for (let i = 0; i <= this.gridLines; i++) {
            const x = (i / this.gridLines) * this.width;
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.height);
            this.ctx.stroke();
        }
    }

    drawAxes() {
        this.ctx.fillStyle = this.textColor;
        this.ctx.font = '11px monospace';
        this.ctx.textAlign = 'right';

        // Y-axis labels (power in dB)
        for (let i = 0; i <= 5; i++) {
            const db = this.maxDb - (i / 5) * (this.maxDb - this.minDb);
            const y = (i / 5) * this.height;
            this.ctx.fillText(db.toFixed(0) + ' dB', this.width - 5, y + 4);
        }

        // X-axis labels (frequency)
        this.ctx.textAlign = 'center';
        const span = this.sampleRate;  // Frequency span
        const startFreq = this.centerFreq - span / 2;

        for (let i = 0; i <= 4; i++) {
            const freq = startFreq + (i / 4) * span;
            const x = (i / 4) * this.width;
            const freqMHz = freq / 1e6;
            this.ctx.fillText(freqMHz.toFixed(2) + ' MHz', x, this.height - 5);
        }
    }

    drawSpectrum() {
        if (!this.spectrum) return;

        const numBins = this.spectrum.length;

        this.ctx.strokeStyle = this.spectrumColor;
        this.ctx.lineWidth = 1.5;
        this.ctx.beginPath();

        for (let i = 0; i < numBins; i++) {
            const x = (i / numBins) * this.width;
            const db = this.spectrum[i];

            // Normalize to canvas height
            let normalized = (db - this.minDb) / (this.maxDb - this.minDb);
            normalized = Math.max(0, Math.min(1, normalized));
            const y = this.height - (normalized * this.height);

            if (i === 0) {
                this.ctx.moveTo(x, y);
            } else {
                this.ctx.lineTo(x, y);
            }
        }

        this.ctx.stroke();

        // Find and display peak
        this.findPeak();
    }

    findPeak() {
        if (!this.spectrum) return;

        let maxPower = -Infinity;
        let maxIndex = 0;

        for (let i = 0; i < this.spectrum.length; i++) {
            if (this.spectrum[i] > maxPower) {
                maxPower = this.spectrum[i];
                maxIndex = i;
            }
        }

        // Calculate frequency of peak
        const span = this.sampleRate;
        const startFreq = this.centerFreq - span / 2;
        const peakFreq = startFreq + (maxIndex / this.spectrum.length) * span;

        // Update UI
        document.getElementById('peak-freq').textContent =
            `Peak: ${(peakFreq / 1e6).toFixed(3)} MHz`;
        document.getElementById('peak-power').textContent =
            `Power: ${maxPower.toFixed(1)} dB`;
    }

    setScale(minDb, maxDb) {
        this.minDb = minDb;
        this.maxDb = maxDb;
    }
}
