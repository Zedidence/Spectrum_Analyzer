# Spectrum Analyzer — Bug Tracker

Comprehensive code review performed 2026-02-13 after v2.0 rebuild.
All bugs fixed 2026-02-19.

---

## Tier 1 — Critical (crashes, disconnects, corrupt display)

### BUG-01: Sweep segment header size mismatch
- **File:** `static/js/modules/protocol.js:14`
- **Status:** [x] Fixed
- **Description:** `SWEEP_SEGMENT_HEADER_SIZE = 48` but the Python backend packs `!IHHddddI` = **44 bytes**. Every sweep segment is parsed with a 4-byte offset, corrupting the entire panorama display.
- **Fix:** Changed to `SWEEP_SEGMENT_HEADER_SIZE = 44`.

### BUG-02: Spectrum Float32Array is a view, not a copy
- **File:** `static/js/modules/protocol.js:96`
- **Status:** [x] Fixed
- **Description:** `new Float32Array(buffer, offset, len)` creates a *view* over the WebSocket buffer. The buffer can be overwritten by the next message before `requestAnimationFrame` renders it, causing intermittent visual corruption (random spikes, glitches). The sweep path at line 158 correctly uses `buffer.slice()` but the main spectrum path and peak hold path do not.
- **Fix:** Changed to `new Float32Array(buffer.slice(offset, offset + byteLen))` for spectrum and peakHold.

### BUG-03: Broadcast loop drops sweep segments
- **File:** `backend/streaming/manager.py` (`_broadcast_loop`)
- **Status:** [x] Fixed
- **Description:** `_broadcast_loop` drains the queue to keep only the latest packet. Correct for live spectrum, but sweep segments represent different frequency bands — dropping any causes gaps in the panorama display.
- **Fix:** Only drains to latest when not in sweep mode (`not self._sweep_active`).

### BUG-04: Triple stop()/wait() with race condition on flowgraph
- **File:** `backend/hardware/bladerf_interface.py:155-178, 207-226`
- **Status:** [x] Fixed
- **Description:** `stop()` calls `_flowgraph.stop()`, the thread's `finally` block calls it again, then `_destroy_flowgraph()` calls it a third time. GNU Radio's `stop()` is not always idempotent. Additionally, `_destroy_flowgraph()` sets `self._flowgraph = None` while the thread's `finally` may still be accessing it. If the thread join times out, both paths manipulate the flowgraph simultaneously.
- **Fix:** Consolidated shutdown — `stop()` signals + joins thread, thread's `finally` does `fg.stop()/fg.wait()`, new `_release_flowgraph_refs()` only nulls references after thread confirmed dead.

### BUG-05: Device probe steals the BladeRF handle
- **File:** `backend/api/routes.py:27-35`
- **Status:** [x] Fixed
- **Description:** `/api/check_device` calls `probe_bladerf_devices()` which opens the BladeRF while the flowgraph already has it open. BladeRF doesn't support multiple simultaneous handles — this can crash the running stream.
- **Fix:** `check_device` now checks `manager.is_streaming` first and returns status from the existing handle if streaming.

### BUG-06: Reconnect endpoint doesn't actually reconnect
- **File:** `backend/api/routes.py:37-51`
- **Status:** [x] Fixed
- **Description:** Calls `cleanup()` (destroying internal state) then `probe_bladerf_devices()`, but the probe result is discarded. The `BladeRFInterface` is left in a half-destroyed state.
- **Fix:** After probe confirms device presence, creates new `BladeRFInterface` and updates `app.state.bladerf` and `manager._bladerf`.

### BUG-07: Sweep completion doesn't restore live mode
- **File:** `backend/sweep/engine.py:297-311`
- **Status:** [x] Fixed
- **Description:** When a survey sweep finishes naturally, `_on_sweep_complete` sets mode to "off" but never calls `resume()` or restores the original sample rate. The BladeRF stays at the sweep sample rate and the live DSP pipeline stays paused — user sees nothing.
- **Fix:** `_on_sweep_complete` now restores sample rate and calls `self._manager.resume()`.

### BUG-08: Single bad JSON kills the WebSocket connection
- **File:** `backend/api/websocket.py:363-364`
- **Status:** [x] Fixed
- **Description:** `json.JSONDecodeError` is caught but falls through to `finally` which calls `remove_client(ws)`, disconnecting the client entirely.
- **Fix:** Added `continue` after the warning log so the loop keeps processing.

### BUG-09: Stacked WebSocket reconnection attempts
- **File:** `static/js/modules/connection.js:46-57`
- **Status:** [x] Fixed
- **Description:** No guard against concurrent reconnects. Multiple `setTimeout` callbacks can create orphaned WebSocket connections whose event handlers still fire. `this._ws` is overwritten but old sockets' handlers still reference `this`.
- **Fix:** Added `_reconnectTimer` tracking; `connect()` cancels pending timer and closes old socket with nulled handlers before replacing.

---

## Tier 2 — High (incorrect data, math errors, thread safety)

### BUG-10: Averaging in dB domain throughout the pipeline
- **File:** `backend/dsp/pipeline.py:146, 236-252`
- **Status:** [x] Fixed
- **Description:** Overlap averaging, linear averaging, and EMA all operate on dBFS values. This is mathematically wrong — averaging dB values underestimates strong signals and overestimates weak ones. The sweep engine (`engine.py:250-259`) and detection (`detector.py:126`) have the same issue.
- **Fix:** Refactored pipeline to compute/average in linear power domain; dB conversion after averaging. Applied consistently across pipeline, sweep engine, and detector.

### BUG-11: Crossfade blending in dB domain
- **File:** `backend/sweep/stitcher.py:149-153`
- **Status:** [x] Fixed
- **Description:** Linear interpolation of dB values creates visible dips/spikes at segment boundaries (up to +3 dB inflation). The taper weights sum to >1 because `prev_edge` data is un-tapered.
- **Fix:** Crossfade now converts to linear power before blending, converts back to dB after.

### BUG-12: Sweep first step misaligned
- **File:** `backend/sweep/stitcher.py:38`
- **Status:** [x] Fixed
- **Description:** First center placed at `freq_start + half_bw` instead of `freq_start + usable_bw/2`, leaving the first ~2 MHz of the requested range uncovered.
- **Fix:** Changed to `freq_start + usable_bw / 2`.

### BUG-13: `threading.Lock` held across `await` in sweep engine
- **File:** `backend/sweep/engine.py:80, 148`
- **Status:** [x] Fixed
- **Description:** `_mode_lock` is a `threading.Lock` but `start()`/`stop()` hold it across `await` calls (`manager.pause()`, `manager.resume()`). This blocks the asyncio event loop and can deadlock.
- **Fix:** Changed `_mode_lock` from `threading.Lock` to `asyncio.Lock`, all usages to `async with`.

### BUG-14: Queue mismatch after sweep stop
- **File:** `backend/sweep/engine.py:100-112, 166-180`
- **Status:** [x] Fixed
- **Description:** Sweep `start()` creates a new `iq_queue` but after `stop()`, `StreamManager._iq_queue` may still point to the old one, preventing live data from flowing.
- **Fix:** Saves `_original_iq_queue` in `start()`, restores it in `stop()`.

### BUG-15: PanoramaRenderer `_buildFromSegments` allocates wrong-sized array
- **File:** `static/js/rendering/panorama-renderer.js:198-226`
- **Status:** [x] Fixed
- **Description:** Sums only *received* segment lengths for allocation but iterates over *total* segments including gaps, causing out-of-bounds writes and distorted rendering.
- **Fix:** Now allocates `totalSegments * segSize` and uses `i * segSize` offset for each segment.

### BUG-16: `DataSink._buffer` grows unboundedly with O(n^2) copies
- **File:** `backend/hardware/bladerf_interface.py:40-55`
- **Status:** [x] Fixed
- **Description:** `np.concatenate` on every `work()` call is O(n^2). At 2 MS/s, if the queue backs up for 10 seconds, this is 160 MB with quadratic-cost copies.
- **Fix:** Replaced with pre-allocated ring buffer with write pointer; grows only if needed (rare).

### BUG-17: `set_fft_size` mutates manager internals without synchronization
- **File:** `backend/api/websocket.py:83-95`
- **Status:** [x] Fixed
- **Description:** Directly writes to `manager._dsp` from the asyncio thread while the DSP thread reads it. The `is_streaming` check-then-act is not atomic.
- **Fix:** Added `set_dsp()` public method on manager; WebSocket handler uses it instead of direct attribute mutation.

### BUG-18: Signal detection center frequency off by half a bin
- **File:** `backend/detection/detector.py:122`
- **Status:** [x] Fixed
- **Description:** Uses `(start_bin + end_bin) / 2` but `end_bin` is exclusive, so the result is consistently high by `bin_width / 2`.
- **Fix:** Changed to `(start_bin + end_bin - 1) / 2`.

### BUG-19: Downsampler truncates trailing bins with non-integer ratios
- **File:** `backend/dsp/downsampler.py:38-41`
- **Status:** [x] Fixed
- **Description:** With non-integer ratios (e.g. 4096 to 3000), the upper ~25% of the spectrum is silently dropped instead of properly resampled.
- **Fix:** Replaced with floating-point bin mapping loop that covers the entire input spectrum.

---

## Tier 3 — Medium (UX, robustness, minor correctness)

### BUG-20: `dbRangeAdjust` only fires once per direction
- **File:** `static/js/modules/state.js:69`, `static/js/main.js:282-296`
- **Status:** [x] Fixed
- **Description:** `StateStore.set()` has `if (old === value) return;` which prevents repeated keypresses of `+`/`-` from adjusting the dB range.
- **Fix:** Added `fire()` method that always triggers listeners (bypasses equality check); keyboard handler uses `fire()`.

### BUG-21: Keyboard auto-scale toggle doesn't sync checkbox
- **File:** `static/js/modules/keyboard.js:120-126`
- **Status:** [x] Fixed
- **Description:** Pressing `A` toggles auto-scale state but never updates `#auto-scale-toggle` checkbox, so the UI shows the wrong state.
- **Fix:** Added checkbox sync when 'A' is pressed.

### BUG-22: Panorama sweep progress line ignores zoom
- **File:** `static/js/rendering/panorama-renderer.js:296-306`
- **Status:** [x] Fixed
- **Description:** Maps sweep progress directly to pixels without accounting for the current zoom/pan view transform.
- **Fix:** Progress line now maps through view transform: `((progress - viewStart) / viewSpan) * w`.

### BUG-23: Path traversal in `rec_delete` WebSocket command
- **File:** `backend/api/websocket.py:296-299`
- **Status:** [x] Fixed
- **Description:** Unlike the REST endpoint which sanitizes with `Path(filename).name`, the WebSocket handler passes `msg['filename']` directly to `delete_recording`.
- **Fix:** Added `Path(msg['filename']).name` sanitization before passing to `delete_recording`.

### BUG-24: SQLite called from DSP thread blocks processing
- **File:** `backend/streaming/manager.py:399-410`
- **Status:** [x] Fixed
- **Description:** Signal detection database I/O blocks the DSP thread. On an RPi with a slow SD card, this can cause IQ data drops.
- **Fix:** Offloaded DB writes to asyncio thread via `call_soon_threadsafe`.

### BUG-25: Storage limit checked per-file, not total
- **File:** `backend/recording/iq_recorder.py:227-232`
- **Status:** [x] Fixed
- **Description:** Compares single recording's `_bytes_written` against the total storage limit, allowing a recording to exceed total capacity when other recordings exist.
- **Fix:** Tracks `_initial_usage` at recording start, checks `_bytes_written + _initial_usage >= max_bytes`.

### BUG-26: `asyncio.get_event_loop()` deprecated
- **File:** `backend/app.py:57`
- **Status:** [x] Fixed
- **Description:** Should be `asyncio.get_running_loop()` inside the running lifespan context (Python 3.10+).
- **Fix:** Replaced with `asyncio.get_running_loop()`.

### BUG-27: No validation on sweep config from WebSocket
- **File:** `backend/api/websocket.py:130-144`
- **Status:** [x] Fixed
- **Description:** `freq_start > freq_end`, `fft_size=0`, or negative values would cause division-by-zero or infinite loops in the sweep engine.
- **Fix:** Added validation for freq_start < freq_end, fft_size power of 2, positive sample_rate and averages.

### BUG-28: Unsynchronized file seek during playback
- **File:** `backend/recording/playback.py:199-219`
- **Status:** [x] Fixed
- **Description:** `seek()` and the playback loop thread both access the same file object from different threads without coordination.
- **Fix:** `seek()` now holds lock around `file.seek` and state update; playback loop reads file under lock.

### BUG-29: Race condition on sweep mode reset without lock
- **File:** `backend/sweep/engine.py:307-311`
- **Status:** [x] Fixed
- **Description:** `_on_sweep_complete` sets `self._mode = "off"` via `call_soon_threadsafe` without holding `_mode_lock`. If `start()` runs concurrently, the mode can be overwritten after the check.
- **Fix:** `_on_sweep_complete` now uses `async with self._mode_lock` (addressed together with BUG-13's asyncio.Lock migration).

### BUG-30: `_syncSelect` has no proximity threshold
- **File:** `static/js/modules/controls.js:525-550`
- **Status:** [x] Fixed
- **Description:** If the server reports a value not in the dropdown, the "closest" numeric match could be wildly wrong (e.g. 40 MS/s silently selects 20 MS/s).
- **Fix:** Added 10% proximity threshold with console warning when no option is close enough.

### BUG-31: Shutdown delay — DSP thread waits 1s for data that will never come
- **File:** `backend/streaming/manager.py:156-166`
- **Status:** [x] Fixed
- **Description:** `_dsp_running` is cleared, then BladeRF is stopped. If the DSP thread is blocked on `queue.get(timeout=1.0)`, it waits the full timeout for data that will never arrive.
- **Fix:** Puts sentinel `None` into `_iq_queue` on stop; DSP loop checks for `None` and breaks immediately.

### BUG-32: WebGL waterfall fallback is a stub
- **File:** `static/js/rendering/waterfall-renderer.js:338-341`
- **Status:** [x] Fixed
- **Description:** On systems without WebGL, the waterfall canvas is simply blank — `addLine()` and `render()` both return early when `_fallback` is true. No error message is shown.
- **Fix:** Implemented Canvas2D fallback with `_fallbackAddLine()` (ring buffer history) and `_fallbackRender()` (ImageData-based colormap rendering).

### BUG-33: `DSPPipeline.set_param()` not thread-safe
- **File:** `backend/dsp/pipeline.py:278+`, called from `backend/api/websocket.py:99-100`
- **Status:** [x] Fixed
- **Description:** `set_param` mutates `_window`, `_avg_mode`, `_ema_state` etc. from the asyncio thread while `process()` reads them on the DSP thread. A partial update (e.g. `_window_type` updated but `_window` array still old) can cause inconsistent processing.
- **Fix:** Added `threading.Lock`; `process()` and `set_param()` both acquire lock around shared mutable state access. `reset()` also protected.

### BUG-34: Sweep loop condition uses full BW instead of usable BW
- **File:** `backend/sweep/stitcher.py:39`
- **Status:** [x] Fixed
- **Description:** `while current_center - half_bw < freq_end` checks full bandwidth, not usable bandwidth. The last step may extend well past `freq_end`, wasting time on data outside the requested range.
- **Fix:** Changed to `current_center - usable_bw / 2 < freq_end`.

### BUG-35: CSS `overflow: hidden` on body prevents scrolling on small viewports
- **File:** `static/css/style.css:82`
- **Status:** [x] Fixed
- **Description:** Combined with the responsive breakpoint layout, content can be clipped with no way to reach it on tablets or small screens.
- **Fix:** Changed to `overflow: auto`.
