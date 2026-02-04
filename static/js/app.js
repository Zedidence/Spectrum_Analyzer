/**
 * Main Application Logic
 * Handles WebSocket communication and UI controls
 *
 * This is the main frontend controller that:
 * - Manages WebSocket connection to Flask backend
 * - Receives real-time FFT data and updates displays
 * - Handles user input and sends control commands
 */

// ============================================================================
// Global Variables
// ============================================================================

let socket = null;                    // Socket.IO connection
let spectrumDisplay = null;           // Spectrum display renderer
let waterfallDisplay = null;          // Waterfall display renderer
let isStreaming = false;              // Current streaming state
let updateCount = 0;                  // FFT update counter
let lastUpdateTime = Date.now();     // Last update timestamp
let dataReceivedCount = 0;            // Total data packets received
let connectionAttempts = 0;           // Connection retry counter

// ============================================================================
// Application Initialization
// ============================================================================

// Initialize application when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('════════════════════════════════════════════════════════');
    console.log('SPECTRUM ANALYZER - Frontend Initialization');
    console.log('════════════════════════════════════════════════════════');

    try {
        // Initialize display renderers
        console.log('Step 1: Creating spectrum display...');
        spectrumDisplay = new SpectrumDisplay('spectrum-canvas');
        console.log('✓ Spectrum display created');

        console.log('Step 2: Creating waterfall display...');
        waterfallDisplay = new WaterfallDisplay('waterfall-canvas', 500);
        console.log('✓ Waterfall display created');

        // Initialize WebSocket connection
        console.log('Step 3: Initializing WebSocket connection...');
        initWebSocket();

        // Setup UI event listeners
        console.log('Step 4: Setting up UI controls...');
        setupControls();
        console.log('✓ UI controls initialized');

        console.log('════════════════════════════════════════════════════════');
        console.log('✓ Initialization complete');
        console.log('════════════════════════════════════════════════════════');
    } catch (error) {
        console.error('✗ Initialization failed:', error);
    }
});

// ============================================================================
// WebSocket Management
// ============================================================================

function initWebSocket() {
    /**
     * Initialize WebSocket (Socket.IO) connection to backend.
     *
     * Sets up event handlers for:
     * - Connection/disconnection
     * - FFT data reception
     * - Status updates
     * - Error messages
     */

    connectionAttempts++;
    console.log(`Connecting to Socket.IO server (attempt ${connectionAttempts})...`);

    // Connect to Socket.IO server (same host as web page)
    socket = io({
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: 10
    });

    // ========================================================================
    // Connection Events
    // ========================================================================

    socket.on('connect', function() {
        console.log('✓ WebSocket connected successfully');
        console.log(`  Socket ID: ${socket.id}`);
        console.log(`  Transport: ${socket.io.engine.transport.name}`);
        updateConnectionStatus(true);

        // Request current device status
        console.log('Requesting device status...');
        socket.emit('get_status');
    });

    socket.on('disconnect', function(reason) {
        console.warn('✗ WebSocket disconnected');
        console.warn(`  Reason: ${reason}`);
        updateConnectionStatus(false);

        // Update UI state
        isStreaming = false;
        updateStreamingButtons();
    });

    socket.on('connect_error', function(error) {
        console.error('✗ Connection error:', error);
    });

    socket.on('reconnect', function(attemptNumber) {
        console.log(`✓ Reconnected after ${attemptNumber} attempts`);
    });

    socket.on('reconnect_attempt', function(attemptNumber) {
        console.log(`Reconnection attempt ${attemptNumber}...`);
    });

    // ========================================================================
    // Data Events
    // ========================================================================

    socket.on('connected', function(data) {
        console.log('✓ Server handshake:', data.message);
    });

    socket.on('fft_data', function(data) {
        /**
         * Handle incoming FFT data from backend.
         * This is the main data stream for spectrum/waterfall displays.
         */

        // Log first packet and periodically thereafter
        dataReceivedCount++;
        if (dataReceivedCount === 1) {
            console.log('✓ First FFT data packet received!');
            console.log('  Spectrum bins:', data.spectrum ? data.spectrum.length : 0);
            console.log('  Center freq:', (data.center_freq / 1e6).toFixed(3), 'MHz');
            console.log('  Sample rate:', (data.sample_rate / 1e6).toFixed(2), 'MS/s');
        }

        if (dataReceivedCount % 100 === 0) {
            console.log(`📊 Received ${dataReceivedCount} FFT packets`);
        }

        // Process FFT data
        handleFFTData(data);
    });

    socket.on('status_update', function(data) {
        /**
         * Handle device status updates.
         * These are sent on connection and when parameters change.
         */
        console.log('📋 Status update:', data);
        updateStatus(data);
    });

    socket.on('error', function(data) {
        /**
         * Handle error messages from backend.
         */
        console.error('❌ Server error:', data.message);
        alert('Error: ' + data.message);
    });

    console.log('✓ WebSocket event handlers registered');
}

// ============================================================================
// Data Handling
// ============================================================================

function handleFFTData(data) {
    /**
     * Process incoming FFT data and update displays.
     *
     * This function:
     * 1. Extracts spectrum, frequency, and sample rate from data packet
     * 2. Updates spectrum display (top panel)
     * 3. Adds new line to waterfall display (bottom panel)
     * 4. Calculates and displays update rate
     *
     * @param {Object} data - FFT data packet from backend
     */

    try {
        // Extract data
        const spectrum = data.spectrum;
        const centerFreq = data.center_freq;
        const sampleRate = data.sample_rate;

        // Validate data
        if (!spectrum || spectrum.length === 0) {
            console.warn('⚠ Received empty spectrum data');
            return;
        }

        // Log data details periodically
        if (dataReceivedCount % 100 === 0) {
            console.log(`Processing FFT data:
  Bins: ${spectrum.length}
  Freq: ${(centerFreq/1e6).toFixed(3)} MHz
  Rate: ${(sampleRate/1e6).toFixed(2)} MS/s
  Min: ${Math.min(...spectrum).toFixed(1)} dB
  Max: ${Math.max(...spectrum).toFixed(1)} dB`);
        }

        // Update spectrum display (top panel)
        spectrumDisplay.updateData(spectrum, centerFreq, sampleRate);

        // Add new line to waterfall display (bottom panel)
        waterfallDisplay.addLine(spectrum);

        // Calculate and display update rate (FPS)
        updateCount++;
        const now = Date.now();
        if (now - lastUpdateTime >= 1000) {
            const fps = updateCount / ((now - lastUpdateTime) / 1000);
            document.getElementById('update-rate').textContent = fps.toFixed(1) + ' Hz';

            if (updateCount % 10 === 0) {
                console.log(`📈 Display update rate: ${fps.toFixed(1)} Hz`);
            }

            updateCount = 0;
            lastUpdateTime = now;
        }

    } catch (error) {
        console.error('✗ Error processing FFT data:', error);
    }
}

function updateStatus(status) {
    // Update device info display
    if (status.sample_rate) {
        const sr = status.sample_rate / 1e6;
        document.getElementById('sample-rate').textContent = sr.toFixed(2) + ' MS/s';
    }

    if (status.fft_size) {
        document.getElementById('fft-size').textContent = status.fft_size;
    }

    if (status.center_freq) {
        const freqMHz = status.center_freq / 1e6;
        document.getElementById('frequency').value = freqMHz;
    }

    if (status.gain !== undefined) {
        document.getElementById('gain').value = status.gain;
        document.getElementById('gain-value').textContent = status.gain;
    }

    if (status.bandwidth) {
        document.getElementById('bandwidth').value = status.bandwidth;
    }

    if (status.streaming !== undefined) {
        isStreaming = status.streaming;
        updateStreamingButtons();
    }
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById('status-indicator');
    const text = document.getElementById('status-text');

    if (connected) {
        indicator.className = 'status-indicator connected';
        text.textContent = 'Connected';
    } else {
        indicator.className = 'status-indicator disconnected';
        text.textContent = 'Disconnected';
    }
}

function updateStreamingButtons() {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');

    if (isStreaming) {
        startBtn.disabled = true;
        stopBtn.disabled = false;
    } else {
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
}

function setupControls() {
    // Start button
    document.getElementById('start-btn').addEventListener('click', function() {
        console.log('Starting streaming');
        socket.emit('start_streaming');
        waterfallDisplay.clear();
    });

    // Stop button
    document.getElementById('stop-btn').addEventListener('click', function() {
        console.log('Stopping streaming');
        socket.emit('stop_streaming');
    });

    // Frequency control
    document.getElementById('frequency').addEventListener('change', function() {
        const freqMHz = parseFloat(this.value);
        const freqHz = freqMHz * 1e6;
        console.log('Setting frequency:', freqMHz, 'MHz');
        socket.emit('set_frequency', { frequency: freqHz });
    });

    // Preset frequency buttons
    document.querySelectorAll('.btn-preset').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const freq = parseFloat(this.dataset.freq);
            document.getElementById('frequency').value = freq;
            socket.emit('set_frequency', { frequency: freq * 1e6 });
        });
    });

    // Bandwidth control
    document.getElementById('bandwidth').addEventListener('change', function() {
        const bw = parseFloat(this.value);
        console.log('Setting bandwidth:', bw / 1e6, 'MHz');
        socket.emit('set_bandwidth', { bandwidth: bw });
    });

    // Gain control
    document.getElementById('gain').addEventListener('input', function() {
        const gain = parseFloat(this.value);
        document.getElementById('gain-value').textContent = gain;
    });

    document.getElementById('gain').addEventListener('change', function() {
        const gain = parseFloat(this.value);
        console.log('Setting gain:', gain, 'dB');
        socket.emit('set_gain', { gain: gain });
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Arrow keys for frequency tuning (when not in input field)
        if (document.activeElement.tagName !== 'INPUT') {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                adjustFrequency(1);  // +1 MHz
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                adjustFrequency(-1);  // -1 MHz
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                adjustFrequency(0.1);  // +0.1 MHz
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                adjustFrequency(-0.1);  // -0.1 MHz
            } else if (e.key === ' ') {
                // Spacebar: toggle streaming
                e.preventDefault();
                if (isStreaming) {
                    document.getElementById('stop-btn').click();
                } else {
                    document.getElementById('start-btn').click();
                }
            }
        }
    });
}

function adjustFrequency(deltaMHz) {
    const freqInput = document.getElementById('frequency');
    let freq = parseFloat(freqInput.value);
    freq += deltaMHz;

    // Clamp to valid range
    freq = Math.max(20, Math.min(6000, freq));

    freqInput.value = freq.toFixed(3);
    socket.emit('set_frequency', { frequency: freq * 1e6 });
}

// Helper: Format frequency for display
function formatFrequency(freqHz) {
    if (freqHz >= 1e9) {
        return (freqHz / 1e9).toFixed(3) + ' GHz';
    } else if (freqHz >= 1e6) {
        return (freqHz / 1e6).toFixed(3) + ' MHz';
    } else if (freqHz >= 1e3) {
        return (freqHz / 1e3).toFixed(3) + ' kHz';
    } else {
        return freqHz.toFixed(0) + ' Hz';
    }
}

console.log('Application initialized');
