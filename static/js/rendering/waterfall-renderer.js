/**
 * WebGL Waterfall Display.
 *
 * GPU-accelerated spectrogram using ring-buffer texture.
 * Ported from the original waterfall-webgl.js with improvements:
 * - WebGL context loss/restore handling
 * - Proper ResizeObserver
 * - ES6 module
 */

import { generateColormapRGBA } from './colormap.js';

export class WaterfallRenderer {
    /**
     * @param {HTMLCanvasElement} canvas
     * @param {number} maxHistory - Maximum history lines (texture height)
     */
    constructor(canvas, maxHistory = 200) {
        this._canvas = canvas;
        this._maxHistory = maxHistory;
        this._numBins = 1024;
        this._minDb = -100;
        this._maxDb = -20;
        this._currentLine = 0;
        this._scrollOffset = 0;
        this._linesAdded = 0;
        this._hasData = false;

        // Try WebGL
        this._gl = canvas.getContext('webgl2') ||
                   canvas.getContext('webgl') ||
                   canvas.getContext('experimental-webgl');

        if (!this._gl) {
            console.warn('WebGL not available for waterfall');
            this._fallback = true;
            this._initCanvas2DFallback();
            return;
        }

        this._fallback = false;
        this._isWebGL2 = this._gl instanceof WebGL2RenderingContext;

        // Context loss handling
        canvas.addEventListener('webglcontextlost', (e) => {
            e.preventDefault();
            console.warn('WebGL context lost');
            this._contextLost = true;
        });
        canvas.addEventListener('webglcontextrestored', () => {
            console.log('WebGL context restored');
            this._contextLost = false;
            this._initWebGL();
        });

        this._contextLost = false;
        this._initWebGL();
        this._initResize();
    }

    _initWebGL() {
        const gl = this._gl;

        // Float texture support
        if (!this._isWebGL2) {
            this._useFloat = !!gl.getExtension('OES_texture_float');
        } else {
            this._useFloat = true;
        }

        // Shader program
        this._program = this._createShaderProgram();
        if (!this._program) {
            console.error('Failed to create waterfall shader');
            return;
        }

        // Uniforms
        this._uniforms = {
            historyTexture: gl.getUniformLocation(this._program, 'historyTexture'),
            colormapTexture: gl.getUniformLocation(this._program, 'colormapTexture'),
            scrollOffset: gl.getUniformLocation(this._program, 'scrollOffset'),
            minDb: gl.getUniformLocation(this._program, 'minDb'),
            maxDb: gl.getUniformLocation(this._program, 'maxDb'),
            hasData: gl.getUniformLocation(this._program, 'hasData'),
        };

        this._posAttrib = gl.getAttribLocation(this._program, 'position');

        // Textures
        this._historyTex = this._createHistoryTexture();
        this._colormapTex = this._createColormapTexture();

        // Fullscreen quad
        const verts = new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]);
        this._quadBuf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, this._quadBuf);
        gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
    }

    _createShaderProgram() {
        const gl = this._gl;

        const vSrc = `
            attribute vec2 position;
            varying vec2 uv;
            void main() {
                uv = position * 0.5 + 0.5;
                gl_Position = vec4(position, 0.0, 1.0);
            }
        `;

        const fSrc = `
            precision highp float;
            uniform sampler2D historyTexture;
            uniform sampler2D colormapTexture;
            uniform float scrollOffset;
            uniform float minDb;
            uniform float maxDb;
            uniform bool hasData;
            varying vec2 uv;

            void main() {
                if (!hasData) {
                    gl_FragColor = vec4(0.039, 0.055, 0.153, 1.0);
                    return;
                }
                vec2 scrolledUV = vec2(uv.x, fract(1.0 - uv.y + scrollOffset));
                float power = texture2D(historyTexture, scrolledUV).r;
                float normalized = clamp((power - minDb) / (maxDb - minDb), 0.0, 1.0);
                vec4 color = texture2D(colormapTexture, vec2(normalized, 0.5));
                gl_FragColor = color;
            }
        `;

        const vs = gl.createShader(gl.VERTEX_SHADER);
        gl.shaderSource(vs, vSrc);
        gl.compileShader(vs);
        if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) {
            console.error('Vertex shader:', gl.getShaderInfoLog(vs));
            return null;
        }

        const fs = gl.createShader(gl.FRAGMENT_SHADER);
        gl.shaderSource(fs, fSrc);
        gl.compileShader(fs);
        if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) {
            console.error('Fragment shader:', gl.getShaderInfoLog(fs));
            return null;
        }

        const prog = gl.createProgram();
        gl.attachShader(prog, vs);
        gl.attachShader(prog, fs);
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
            console.error('Program link:', gl.getProgramInfoLog(prog));
            return null;
        }

        return prog;
    }

    _createHistoryTexture() {
        const gl = this._gl;
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);

        // Filtering
        const canFilterFloat = !!gl.getExtension('OES_texture_float_linear');
        const filter = canFilterFloat ? gl.LINEAR : gl.NEAREST;
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);

        // Initialize with minimum dB
        const initData = new Float32Array(this._numBins * this._maxHistory).fill(-120);

        if (this._isWebGL2) {
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F,
                this._numBins, this._maxHistory, 0,
                gl.RED, gl.FLOAT, initData);
        } else if (this._useFloat) {
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE,
                this._numBins, this._maxHistory, 0,
                gl.LUMINANCE, gl.FLOAT, initData);
        } else {
            const byteData = new Uint8Array(this._numBins * this._maxHistory);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE,
                this._numBins, this._maxHistory, 0,
                gl.LUMINANCE, gl.UNSIGNED_BYTE, byteData);
        }

        return tex;
    }

    _createColormapTexture() {
        const gl = this._gl;
        const tex = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, tex);

        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

        const colormapData = generateColormapRGBA();
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0,
            gl.RGBA, gl.UNSIGNED_BYTE, colormapData);

        return tex;
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

                if (this._gl) {
                    this._gl.viewport(0, 0, this._canvas.width, this._canvas.height);
                }
            }
        });
        observer.observe(this._canvas.parentElement);
    }

    /**
     * Add a new spectrum line to the waterfall.
     * @param {Float32Array} spectrum
     */
    addLine(spectrum) {
        if (this._contextLost || this._fallback) return;

        // Handle bin count changes
        if (spectrum.length !== this._numBins) {
            this._numBins = spectrum.length;
            if (this._historyTex) {
                this._gl.deleteTexture(this._historyTex);
            }
            this._historyTex = this._createHistoryTexture();
            this._currentLine = 0;
        }

        const gl = this._gl;
        const data = spectrum instanceof Float32Array ? spectrum : new Float32Array(spectrum);

        gl.bindTexture(gl.TEXTURE_2D, this._historyTex);

        if (this._isWebGL2) {
            gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, this._currentLine,
                this._numBins, 1, gl.RED, gl.FLOAT, data);
        } else if (this._useFloat) {
            gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, this._currentLine,
                this._numBins, 1, gl.LUMINANCE, gl.FLOAT, data);
        } else {
            const byteData = new Uint8Array(this._numBins);
            const dbRange = this._maxDb - this._minDb;
            for (let i = 0; i < this._numBins; i++) {
                let n = (data[i] - this._minDb) / dbRange;
                n = Math.max(0, Math.min(1, n));
                byteData[i] = Math.floor(n * 255);
            }
            gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, this._currentLine,
                this._numBins, 1, gl.LUMINANCE, gl.UNSIGNED_BYTE, byteData);
        }

        this._currentLine = (this._currentLine + 1) % this._maxHistory;
        this._scrollOffset = this._currentLine / this._maxHistory;
        this._linesAdded++;
        this._hasData = true;
    }

    /** Render the waterfall display. */
    render() {
        if (this._contextLost || this._fallback) return;

        const gl = this._gl;
        gl.clearColor(0.039, 0.055, 0.153, 1.0);
        gl.clear(gl.COLOR_BUFFER_BIT);

        gl.useProgram(this._program);

        // Bind textures
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this._historyTex);
        gl.uniform1i(this._uniforms.historyTexture, 0);

        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, this._colormapTex);
        gl.uniform1i(this._uniforms.colormapTexture, 1);

        // Set uniforms
        gl.uniform1f(this._uniforms.scrollOffset, this._scrollOffset);
        gl.uniform1f(this._uniforms.minDb, this._minDb);
        gl.uniform1f(this._uniforms.maxDb, this._maxDb);
        gl.uniform1i(this._uniforms.hasData, this._hasData ? 1 : 0);

        // Draw
        gl.bindBuffer(gl.ARRAY_BUFFER, this._quadBuf);
        gl.enableVertexAttribArray(this._posAttrib);
        gl.vertexAttribPointer(this._posAttrib, 2, gl.FLOAT, false, 0, 0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }

    setScale(minDb, maxDb) {
        this._minDb = minDb;
        this._maxDb = maxDb;
    }

    /**
     * Change the colormap.
     * @param {string} name - Colormap name
     */
    setColormap(name) {
        if (this._fallback || this._contextLost || !this._gl) return;

        const gl = this._gl;
        gl.bindTexture(gl.TEXTURE_2D, this._colormapTex);
        const colormapData = generateColormapRGBA(name);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0,
            gl.RGBA, gl.UNSIGNED_BYTE, colormapData);
    }

    get linesAdded() {
        return this._linesAdded;
    }

    // --- Canvas 2D fallback ---

    _initCanvas2DFallback() {
        this._ctx = this._canvas.getContext('2d');
        // Minimal fallback for systems without WebGL
    }
}
