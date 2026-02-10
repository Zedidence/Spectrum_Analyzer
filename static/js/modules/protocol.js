/**
 * Binary WebSocket protocol parser.
 *
 * Matches the encoding in backend/streaming/protocol.py.
 * All multi-byte values are big-endian (network byte order).
 */

export const VERSION = 0x02;
export const MSG_SPECTRUM = 0x01;
export const FRAME_HEADER_SIZE = 8;
export const SPECTRUM_HEADER_SIZE = 56;

// Flags
export const FLAG_PEAK_HOLD = 0x0001;

/**
 * Parse a binary WebSocket frame.
 *
 * @param {ArrayBuffer} buffer - Raw binary data from WebSocket
 * @returns {Object|null} Parsed frame data or null on error
 */
export function parseFrame(buffer) {
    if (buffer.byteLength < FRAME_HEADER_SIZE) {
        console.warn('Frame too small:', buffer.byteLength);
        return null;
    }

    const view = new DataView(buffer);
    const version = view.getUint8(0);
    const msgType = view.getUint8(1);
    const flags = view.getUint16(2, false); // big-endian
    const payloadLen = view.getUint32(4, false); // big-endian

    if (version !== VERSION) {
        console.warn('Unknown protocol version:', version);
        return null;
    }

    if (buffer.byteLength < FRAME_HEADER_SIZE + payloadLen) {
        console.warn('Incomplete frame:', buffer.byteLength, 'expected:', FRAME_HEADER_SIZE + payloadLen);
        return null;
    }

    if (msgType === MSG_SPECTRUM) {
        return parseSpectrumPayload(buffer, FRAME_HEADER_SIZE, payloadLen, flags);
    }

    return null;
}

/**
 * Parse spectrum payload from within a frame.
 */
function parseSpectrumPayload(buffer, offset, payloadLen, flags) {
    if (payloadLen < SPECTRUM_HEADER_SIZE) {
        console.warn('Spectrum payload too small:', payloadLen);
        return null;
    }

    const view = new DataView(buffer, offset);

    const centerFreq = view.getFloat64(0, false);
    const sampleRate = view.getFloat64(8, false);
    const bandwidth = view.getFloat64(16, false);
    const gain = view.getFloat32(24, false);
    const fftSize = view.getUint32(28, false);
    const numBins = view.getUint32(32, false);
    const noiseFloor = view.getFloat32(36, false);
    const peakPower = view.getFloat32(40, false);
    const peakFreqOffset = view.getFloat32(44, false);
    const timestamp = view.getFloat64(48, false);

    // Spectrum data starts at offset + SPECTRUM_HEADER_SIZE
    const spectrumByteOffset = offset + SPECTRUM_HEADER_SIZE;
    const spectrumByteLength = numBins * 4; // float32

    if (buffer.byteLength < spectrumByteOffset + spectrumByteLength) {
        console.warn('Not enough data for spectrum bins');
        return null;
    }

    const spectrum = new Float32Array(buffer, spectrumByteOffset, numBins);

    // Parse peak hold if flag is set
    let peakHold = null;
    if (flags & FLAG_PEAK_HOLD) {
        const peakHoldByteOffset = spectrumByteOffset + spectrumByteLength;
        const peakHoldByteLength = numBins * 4;
        if (buffer.byteLength >= peakHoldByteOffset + peakHoldByteLength) {
            peakHold = new Float32Array(buffer, peakHoldByteOffset, numBins);
        }
    }

    return {
        type: 'spectrum',
        centerFreq,
        sampleRate,
        bandwidth,
        gain,
        fftSize,
        numBins,
        noiseFloor,
        peakPower,
        peakFreqOffset,
        timestamp,
        spectrum,
        peakHold,
    };
}
