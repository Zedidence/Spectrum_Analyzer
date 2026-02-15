"""
Sweep engine: orchestrates frequency stepping, IQ collection, and panorama assembly.

Runs in its own thread, coordinating with BladeRFInterface for frequency changes
and using a dedicated DSPPipeline instance for per-step FFT processing.

The existing live DSP thread is paused during sweep and resumed when returning
to live mode.
"""

import threading
import queue
import logging
import time
import asyncio
import numpy as np
from typing import Optional

from config import SweepConfig, DSPConfig
from dsp.pipeline import DSPPipeline
from sweep.stitcher import SpectrumStitcher, compute_step_frequencies
from streaming.protocol import encode_sweep_segment_packet, encode_sweep_panorama_packet

logger = logging.getLogger(__name__)


class SweepEngine:
    """
    Frequency sweep coordinator.

    Manages a sweep thread that steps through center frequencies,
    collects and processes IQ data at each step, stitches results
    into a panoramic spectrum, and emits binary packets for display.
    """

    def __init__(self, bladerf, config, loop, stream_manager):
        """
        Args:
            bladerf: BladeRFInterface instance
            config: Top-level Config instance
            loop: asyncio event loop (main thread)
            stream_manager: StreamManager instance (for pause/resume/inject)
        """
        self._bladerf = bladerf
        self._config = config
        self._loop = loop
        self._manager = stream_manager

        # Sweep thread state
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._stop_requested = threading.Event()

        # Sweep state
        self._sweep_id = 0
        self._mode = "off"  # "off", "survey", "band_monitor"
        self._sweep_config: Optional[SweepConfig] = None
        self._current_step = 0
        self._total_steps = 0
        self._last_sweep_duration_ms = 0.0
        self._sweeps_completed = 0

        # Original live-mode state (to restore after sweep)
        self._original_sample_rate = None
        self._original_bandwidth = None
        self._original_iq_queue = None

        # Lock for mode transitions (asyncio.Lock because start/stop are async)
        self._mode_lock = asyncio.Lock()

    async def start(self, sweep_config: SweepConfig):
        """
        Start a sweep. Pauses live mode, configures hardware, begins sweep thread.

        Args:
            sweep_config: SweepConfig with mode, freq range, and parameters

        Returns:
            True if sweep started successfully
        """
        async with self._mode_lock:
            if self._running.is_set():
                logger.warning("Sweep already running")
                return False

            self._sweep_config = sweep_config
            self._mode = sweep_config.mode
            self._stop_requested.clear()

            # Save original sample rate and IQ queue for restoration
            status = self._bladerf.get_status()
            self._original_sample_rate = status['sample_rate']
            self._original_bandwidth = status['bandwidth']
            was_streaming = self._manager.is_streaming
            self._original_iq_queue = self._manager._iq_queue

            # Pause live streaming (keeps flowgraph running, stops DSP thread)
            if was_streaming:
                await self._manager.pause()

            # Change sample rate if needed (requires flowgraph restart)
            if status['sample_rate'] != sweep_config.sweep_sample_rate:
                self._bladerf.stop()
                self._bladerf.set_sample_rate(sweep_config.sweep_sample_rate)
                self._bladerf.set_bandwidth(sweep_config.sweep_sample_rate)

                # Restart flowgraph with new rate
                iq_queue = queue.Queue(maxsize=self._config.iq_queue_size)
                self._bladerf.set_chunk_size(sweep_config.fft_size)
                if not self._bladerf.start(iq_queue):
                    logger.error("Failed to restart BladeRF for sweep")
                    return False
                self._iq_queue = iq_queue
                time.sleep(0.1)  # Let flowgraph stabilize
            elif was_streaming:
                self._iq_queue = self._bladerf.iq_queue
            else:
                # Not streaming — need to start flowgraph
                iq_queue = queue.Queue(maxsize=self._config.iq_queue_size)
                self._bladerf.set_chunk_size(sweep_config.fft_size)
                if not self._bladerf.start(iq_queue):
                    logger.error("Failed to start BladeRF for sweep")
                    return False
                self._iq_queue = iq_queue
                time.sleep(0.1)

            # Ensure broadcast pipeline exists for sweep packet delivery
            await self._manager.ensure_broadcast_pipeline()

            # Start sweep thread
            self._running.set()
            self._sweep_id += 1
            self._thread = threading.Thread(
                target=self._sweep_loop,
                name="sweep-thread",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Sweep started: mode=%s, %.3f-%.3f MHz, %d MS/s",
                sweep_config.mode,
                sweep_config.freq_start / 1e6,
                sweep_config.freq_end / 1e6,
                sweep_config.sweep_sample_rate / 1e6,
            )
            return True

    async def stop(self):
        """Stop any active sweep and restore live mode."""
        async with self._mode_lock:
            if not self._running.is_set():
                return

            logger.info("Stopping sweep...")
            self._stop_requested.set()
            self._running.clear()

            # Wait for sweep thread to finish
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=10.0)
                if self._thread.is_alive():
                    logger.warning("Sweep thread did not exit in 10s")

            self._thread = None
            self._mode = "off"

            # Restore original IQ queue so live data flows correctly
            if self._original_iq_queue is not None:
                self._manager._iq_queue = self._original_iq_queue
                self._original_iq_queue = None

            # Restore original sample rate if it was changed
            status = self._bladerf.get_status()
            if (self._original_sample_rate and
                    status['sample_rate'] != self._original_sample_rate):
                self._bladerf.stop()
                self._bladerf.set_sample_rate(self._original_sample_rate)
                self._bladerf.set_bandwidth(
                    self._original_bandwidth or self._original_sample_rate
                )
                # StreamManager.resume() will restart the flowgraph as needed

            # Clear sweep broadcast flag
            self._manager.end_sweep_broadcast()

            # Resume live streaming
            await self._manager.resume()

            logger.info("Sweep stopped, live mode restored")

    def _sweep_loop(self):
        """Main sweep thread function."""
        config = self._sweep_config
        logger.info("Sweep thread started")

        # Compute step plan
        steps = compute_step_frequencies(
            config.freq_start, config.freq_end,
            config.sweep_sample_rate, config.usable_fraction,
        )
        self._total_steps = len(steps)
        logger.info("Sweep plan: %d steps", self._total_steps)

        # Create sweep-optimized DSP pipeline (no overlap, no averaging — we do our own)
        sweep_dsp_config = DSPConfig(
            fft_size=config.fft_size,
            window_type='blackman-harris',
            averaging_mode='none',
            dc_removal=True,
            target_display_bins=config.fft_size,  # Keep full resolution
        )
        sweep_dsp = DSPPipeline(sweep_dsp_config)
        # Disable overlap for sweep (we want independent per-step FFTs)
        sweep_dsp._overlap_enabled = False

        # Create stitcher
        stitcher = SpectrumStitcher(
            config.freq_start, config.freq_end, steps,
            config.sweep_sample_rate, config.fft_size,
            config.usable_fraction,
        )

        sweep_id = self._sweep_id

        while self._running.is_set() and not self._stop_requested.is_set():
            stitcher.reset()
            sweep_start = time.monotonic()

            for step_idx, center_freq in enumerate(steps):
                if self._stop_requested.is_set():
                    break

                self._current_step = step_idx

                # 1. Retune
                self._bladerf.set_frequency(center_freq)

                # 2. Flush stale IQ data (PLL settling)
                self._flush_iq_queue(config.settle_chunks)

                # 3. Collect and average in linear power domain
                accumulated_linear = None
                valid_count = 0
                for _ in range(config.averages_per_step):
                    if self._stop_requested.is_set():
                        break
                    try:
                        chunk = self._iq_queue.get(timeout=2.0)
                    except queue.Empty:
                        logger.warning("Sweep: IQ queue timeout at step %d", step_idx)
                        continue

                    result = sweep_dsp.process(chunk)
                    if result is None:
                        continue

                    # Convert dBFS back to linear for proper averaging
                    linear = np.power(10.0, result.spectrum / 10.0)
                    if accumulated_linear is None:
                        accumulated_linear = linear
                    else:
                        accumulated_linear += linear
                    valid_count += 1

                if accumulated_linear is None or valid_count == 0:
                    continue

                accumulated_linear /= valid_count
                # Convert back to dBFS
                accumulated = (10.0 * np.log10(np.maximum(accumulated_linear, 1e-20))).astype(np.float32)
                sweep_dsp.reset()  # Reset state between steps

                # 4. Stitch into panorama
                stitcher.add_segment(step_idx, accumulated)

                # 5. Emit incremental segment for survey mode
                if config.mode == 'survey':
                    self._emit_segment(
                        sweep_id, step_idx, self._total_steps,
                        accumulated, center_freq, config,
                    )

            if self._stop_requested.is_set():
                break

            # 6. Emit complete panorama
            sweep_duration_ms = (time.monotonic() - sweep_start) * 1000
            self._last_sweep_duration_ms = sweep_duration_ms
            self._sweeps_completed += 1

            self._emit_panorama(sweep_id, config, stitcher, sweep_duration_ms)

            logger.info(
                "Sweep #%d complete: %d steps in %.0f ms",
                self._sweeps_completed, self._total_steps, sweep_duration_ms,
            )

            # For survey mode: single pass then stop
            if not config.continuous:
                break

            sweep_id += 1
            self._sweep_id = sweep_id

        self._running.clear()
        logger.info("Sweep thread exited (%d sweeps completed)", self._sweeps_completed)

        # If survey mode finished naturally, notify via asyncio
        if not self._stop_requested.is_set() and not config.continuous:
            try:
                self._loop.call_soon_threadsafe(
                    self._loop.create_task,
                    self._on_sweep_complete(),
                )
            except RuntimeError:
                pass

    async def _on_sweep_complete(self):
        """Called when a survey sweep finishes naturally."""
        async with self._mode_lock:
            self._mode = "off"

        self._manager.end_sweep_broadcast()

        # Restore original sample rate if it was changed
        status = self._bladerf.get_status()
        if (self._original_sample_rate and
                status['sample_rate'] != self._original_sample_rate):
            self._bladerf.stop()
            self._bladerf.set_sample_rate(self._original_sample_rate)
            self._bladerf.set_bandwidth(
                self._original_bandwidth or self._original_sample_rate
            )

        # Resume live streaming
        await self._manager.resume()
        logger.info("Survey sweep complete, live mode restored")

    def _flush_iq_queue(self, n_chunks):
        """Discard n_chunks from the IQ queue (post-retune settling)."""
        discarded = 0
        while discarded < n_chunks:
            try:
                self._iq_queue.get(timeout=0.5)
                discarded += 1
            except queue.Empty:
                break
        return discarded

    def _emit_segment(self, sweep_id, step_idx, total_steps,
                      spectrum, center_freq, config):
        """Encode and send incremental sweep segment to clients."""
        usable_fraction = config.usable_fraction
        sample_rate = config.sweep_sample_rate
        trim_bins = int(config.fft_size * (1.0 - usable_fraction) / 2)
        usable_bins = config.fft_size - 2 * trim_bins
        usable = spectrum[trim_bins:trim_bins + usable_bins]

        seg_freq_start = center_freq - sample_rate * usable_fraction / 2
        seg_freq_end = center_freq + sample_rate * usable_fraction / 2

        packet = encode_sweep_segment_packet(
            sweep_id=sweep_id,
            segment_idx=step_idx,
            total_segments=total_steps,
            freq_start=seg_freq_start,
            freq_end=seg_freq_end,
            sweep_start=config.freq_start,
            sweep_end=config.freq_end,
            spectrum=usable,
        )
        self._manager.inject_packet(packet)

    def _emit_panorama(self, sweep_id, config, stitcher, sweep_duration_ms):
        """Encode and send complete stitched panorama to clients."""
        display_freqs, display_power = stitcher.get_display_panorama(
            config.display_bins
        )

        packet = encode_sweep_panorama_packet(
            sweep_id=sweep_id,
            sweep_mode=0 if config.mode == 'survey' else 1,
            freq_start=config.freq_start,
            freq_end=config.freq_end,
            num_bins=len(display_power),
            sweep_time_ms=sweep_duration_ms,
            spectrum=display_power,
        )
        self._manager.inject_packet(packet)

    def get_status(self):
        """Return current sweep state for status API."""
        return {
            'sweep_mode': self._mode,
            'sweep_running': self._running.is_set(),
            'sweep_id': self._sweep_id,
            'sweep_step': self._current_step,
            'sweep_total_steps': self._total_steps,
            'sweep_progress': (
                self._current_step / self._total_steps
                if self._total_steps > 0 else 0
            ),
            'sweep_last_duration_ms': self._last_sweep_duration_ms,
            'sweeps_completed': self._sweeps_completed,
        }
