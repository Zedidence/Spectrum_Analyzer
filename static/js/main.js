/**
 * Spectrum Analyzer v2.0 - Main Entry Point
 *
 * ES6 module that initializes all components and manages the render loop.
 * Integrates: spectrum renderer, waterfall, grid overlay, zoom, markers, keyboard.
 */

import { StateStore } from './modules/state.js';
import { Connection } from './modules/connection.js';
import { Controls } from './modules/controls.js';
import { KeyboardHandler } from './modules/keyboard.js';
import { SpectrumRenderer } from './rendering/spectrum-renderer.js';
import { WaterfallRenderer } from './rendering/waterfall-renderer.js';
import { GridOverlay } from './rendering/grid-overlay.js';
import { ZoomController } from './rendering/zoom-controller.js';
import { MarkerManager } from './analysis/markers.js';

// Initialize state store
const state = new StateStore();

// Initialize renderers
const spectrumCanvas = document.getElementById('spectrum-canvas');
const overlayCanvas = document.getElementById('spectrum-overlay');
const waterfallCanvas = document.getElementById('waterfall-canvas');
const spectrumRenderer = new SpectrumRenderer(spectrumCanvas);
const waterfallRenderer = new WaterfallRenderer(waterfallCanvas, 200);
const gridOverlay = new GridOverlay(overlayCanvas);

// Zoom controller (attached to spectrum stack for mouse events)
const spectrumStack = document.getElementById('spectrum-stack');
const zoomController = new ZoomController(spectrumStack);

// Markers
const markerManager = new MarkerManager();

// Zoom info display
const zoomInfo = document.getElementById('zoom-info');

// Wire zoom changes to renderers
zoomController.onChange((start, end) => {
    spectrumRenderer.setView(start, end);
    if (zoomInfo) {
        if (start > 0.001 || end < 0.999) {
            const pct = ((end - start) * 100).toFixed(1);
            zoomInfo.textContent = `Zoom: ${pct}%`;
        } else {
            zoomInfo.textContent = '';
        }
    }
});

// Render scheduling
let pendingRender = false;
let latestData = null;

// FPS tracking
let frameCount = 0;
let lastFpsTime = performance.now();
let currentFps = 0;

// Track latest center freq and sample rate for markers
let currentCenterFreq = 100e6;
let currentSampleRate = 2e6;

/**
 * Handle incoming spectrum data from WebSocket.
 */
function onSpectrum(data) {
    latestData = data;

    if (!pendingRender) {
        pendingRender = true;
        requestAnimationFrame(renderFrame);
    }
}

/**
 * Render a single frame. Called via requestAnimationFrame.
 */
function renderFrame() {
    pendingRender = false;
    const data = latestData;
    if (!data) return;

    currentCenterFreq = data.centerFreq;
    currentSampleRate = data.sampleRate;

    // Update spectrum renderer
    spectrumRenderer.updateData(
        data.spectrum,
        data.centerFreq,
        data.sampleRate,
        data.peakHold,
    );
    spectrumRenderer.render();

    // Update grid overlay
    gridOverlay.update({
        dbMin: spectrumRenderer.dbMin,
        dbMax: spectrumRenderer.dbMax,
        centerFreq: data.centerFreq,
        sampleRate: data.sampleRate,
        viewStart: zoomController.viewStart,
        viewEnd: zoomController.viewEnd,
        markers: markerManager.markers,
    });
    gridOverlay.render();

    // Update waterfall
    waterfallRenderer.addLine(data.spectrum);
    waterfallRenderer.render();

    // Update marker power levels from latest data
    markerManager.updateFromSpectrum(data.spectrum, data.centerFreq, data.sampleRate);

    // Update state from spectrum data
    state.batch({
        centerFreq: data.centerFreq,
        sampleRate: data.sampleRate,
        noiseFloor: data.noiseFloor,
        peakPower: data.peakPower,
    });

    // FPS tracking
    frameCount++;
    const now = performance.now();
    if (now - lastFpsTime >= 1000) {
        currentFps = frameCount;
        frameCount = 0;
        lastFpsTime = now;

        // Update UI stats
        const peak = spectrumRenderer.getPeakInfo();
        controls.updateStats({
            fps: currentFps,
            peakFreq: peak.freq,
            peakPower: peak.power,
            waterfallLines: Math.min(waterfallRenderer.linesAdded, 200),
        });
    }
}

/**
 * Handle status updates from WebSocket.
 */
function onStatus(data) {
    // Connection status
    if (data.type === 'connection') {
        state.set('connected', data.connected);
        if (data.connected) {
            connection.send('get_status');
            connection.send('check_device');
        }
        return;
    }

    // Server status update
    controls.updateFromStatus(data);
}

/**
 * Handle errors from WebSocket.
 */
function onError(message) {
    console.error('Server error:', message);
}

// Initialize connection
const connection = new Connection(onSpectrum, onStatus, onError);

// Initialize controls
const controls = new Controls(state, connection);

// Initialize keyboard shortcuts
const keyboard = new KeyboardHandler({
    state,
    connection,
    zoom: zoomController,
    markers: markerManager,
    getSpectrum: () => spectrumRenderer.getSpectrum(),
    getCenterFreq: () => currentCenterFreq,
    getSampleRate: () => currentSampleRate,
});

// Handle auto-scale toggle from keyboard or UI
state.on('autoScale', (enabled) => {
    spectrumRenderer.setAutoScale(enabled);
});

// Handle colormap change
state.on('colormap', (name) => {
    waterfallRenderer.setColormap(name);
});

// Handle dB range adjustment from keyboard
state.on('dbRangeAdjust', (direction) => {
    if (spectrumRenderer.autoScale) return;
    const step = 5;
    if (direction === 'narrow') {
        spectrumRenderer.setDbRange(
            spectrumRenderer.dbMin + step,
            spectrumRenderer.dbMax - step,
        );
    } else if (direction === 'widen') {
        spectrumRenderer.setDbRange(
            spectrumRenderer.dbMin - step,
            spectrumRenderer.dbMax + step,
        );
    }
});

// Connect
connection.connect();

// Visibility change: pause rendering when tab is hidden
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        pendingRender = false;
    }
});

// Cleanup on unload
window.addEventListener('beforeunload', () => {
    connection.disconnect();
});

// Debug functions (accessible from browser console)
window.debugApp = () => {
    console.log('State:', {
        connected: state.get('connected'),
        streaming: state.get('streaming'),
        centerFreq: state.get('centerFreq'),
        sampleRate: state.get('sampleRate'),
        gain: state.get('gain'),
        fftSize: state.get('fftSize'),
        fps: currentFps,
        zoom: {
            start: zoomController.viewStart,
            end: zoomController.viewEnd,
        },
        markers: markerManager.markers.length,
        autoScale: spectrumRenderer.autoScale,
        dbRange: [spectrumRenderer.dbMin, spectrumRenderer.dbMax],
    });
};

console.log('Spectrum Analyzer v2.0 initialized');
console.log('Shortcuts: M=marker, N=next peak, D=delta, C=clear, H=peak hold, R=reset zoom, A=auto-scale, +/-=dB range');
