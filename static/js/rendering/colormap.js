/**
 * Colormap generation for waterfall display.
 *
 * Multiple colormaps available: viridis, plasma, inferno, turbo, grayscale.
 */

const COLORMAPS = {
    viridis: generateViridis,
    plasma: generatePlasma,
    inferno: generateInferno,
    turbo: generateTurbo,
    grayscale: generateGrayscale,
};

/**
 * Get list of available colormap names.
 */
export function availableColormaps() {
    return Object.keys(COLORMAPS);
}

/**
 * Generate 256-entry RGBA colormap as Uint8Array (256 * 4 bytes).
 * @param {string} name - Colormap name (default: 'viridis')
 * @returns {Uint8Array} 1024-byte RGBA colormap
 */
export function generateColormapRGBA(name = 'viridis') {
    const generator = COLORMAPS[name] || COLORMAPS.viridis;
    return generator();
}

/**
 * Generate colormap as array of [r,g,b] tuples (for Canvas 2D fallback).
 * @param {string} name
 * @returns {Array<Array<number>>} 256 RGB tuples
 */
export function generateColormapRGB(name = 'viridis') {
    const rgba = generateColormapRGBA(name);
    const rgb = [];
    for (let i = 0; i < 256; i++) {
        rgb.push([rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]]);
    }
    return rgb;
}

// --- Colormap generators ---

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function colormapFromStops(stops) {
    const data = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) {
        const t = i / 255;
        // Find the two stops that bracket t
        let lo = stops[0], hi = stops[stops.length - 1];
        for (let j = 0; j < stops.length - 1; j++) {
            if (t >= stops[j][0] && t <= stops[j + 1][0]) {
                lo = stops[j];
                hi = stops[j + 1];
                break;
            }
        }
        const s = (hi[0] - lo[0]) > 0 ? (t - lo[0]) / (hi[0] - lo[0]) : 0;
        data[i * 4] = Math.floor(lerp(lo[1], hi[1], s));
        data[i * 4 + 1] = Math.floor(lerp(lo[2], hi[2], s));
        data[i * 4 + 2] = Math.floor(lerp(lo[3], hi[3], s));
        data[i * 4 + 3] = 255;
    }
    return data;
}

function generateViridis() {
    // [position, r, g, b]
    return colormapFromStops([
        [0.00, 68, 1, 84],
        [0.25, 59, 82, 139],
        [0.50, 33, 145, 140],
        [0.75, 94, 201, 98],
        [1.00, 253, 231, 37],
    ]);
}

function generatePlasma() {
    return colormapFromStops([
        [0.00, 13, 8, 135],
        [0.25, 126, 3, 168],
        [0.50, 204, 71, 120],
        [0.75, 248, 149, 64],
        [1.00, 240, 249, 33],
    ]);
}

function generateInferno() {
    return colormapFromStops([
        [0.00, 0, 0, 4],
        [0.20, 40, 11, 84],
        [0.40, 120, 28, 109],
        [0.60, 188, 55, 84],
        [0.80, 237, 121, 36],
        [1.00, 252, 255, 164],
    ]);
}

function generateTurbo() {
    return colormapFromStops([
        [0.00, 48, 18, 59],
        [0.15, 67, 97, 238],
        [0.30, 30, 175, 221],
        [0.45, 56, 232, 131],
        [0.60, 177, 242, 53],
        [0.75, 243, 192, 44],
        [0.90, 234, 96, 26],
        [1.00, 122, 4, 3],
    ]);
}

function generateGrayscale() {
    const data = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) {
        data[i * 4] = i;
        data[i * 4 + 1] = i;
        data[i * 4 + 2] = i;
        data[i * 4 + 3] = 255;
    }
    return data;
}
