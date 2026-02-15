"""
StreamManager: Coordinates GNU Radio thread, DSP thread, and asyncio WebSocket.

Data flow:
  BladeRF (GNU Radio thread) --[iq_queue]--> DSP thread --[result_queue]--> asyncio loop

This is the critical module that safely bridges three execution domains:
1. GNU Radio C++ scheduler thread (produces IQ data)
2. DSP processing thread (consumes IQ, produces spectrum)
3. asyncio event loop (broadcasts to WebSocket clients)
"""

import asyncio
import threading
import queue
import logging
import time
import json
from typing import Set, Optional

from fastapi import WebSocket

from config import Config
from hardware.bladerf_interface import BladeRFInterface
from dsp.pipeline import DSPPipeline
from dsp.agc import SoftwareAGC
from streaming.protocol import encode_spectrum_packet

logger = logging.getLogger(__name__)


class StreamManager:
    """Coordinates the full streaming pipeline."""

    def __init__(self, bladerf, dsp, config, loop):
        """
        Args:
            bladerf: BladeRFInterface instance
            dsp: DSPPipeline instance
            config: Config instance
            loop: asyncio event loop (main thread)
        """
        self._bladerf = bladerf
        self._dsp = dsp
        self._config = config
        self._loop = loop

        # IPC queues
        self._iq_queue: Optional[queue.Queue] = None
        self._result_queue: Optional[asyncio.Queue] = None

        # DSP thread
        self._dsp_thread: Optional[threading.Thread] = None
        self._dsp_running = threading.Event()

        # Connected WebSocket clients
        self._clients: Set[WebSocket] = set()
        self._clients_lock = asyncio.Lock()

        # Broadcast task
        self._broadcast_task: Optional[asyncio.Task] = None

        # AGC
        self._agc = SoftwareAGC()

        # State
        self._streaming = False
        self._paused = False
        self._sweep_active = False

        # Signal detector (set externally after construction)
        self._detector = None
        self._signal_db = None

        # Recording manager (set externally after construction)
        self._recording_manager = None
        self._playback_mode = False

    @property
    def is_streaming(self):
        return self._streaming

    def set_dsp(self, dsp):
        """Replace the DSP pipeline (only when not streaming)."""
        if self._streaming:
            raise RuntimeError("Cannot replace DSP pipeline while streaming")
        self._dsp = dsp

    @property
    def agc(self):
        return self._agc

    @property
    def detector(self):
        return self._detector

    def set_detector(self, detector, database=None):
        """Set the signal detector and optional database for persistence."""
        self._detector = detector
        self._signal_db = database

    def set_recording_manager(self, recording_manager):
        """Set the recording manager for IQ/spectrum recording and playback."""
        self._recording_manager = recording_manager

    @property
    def playback_mode(self):
        return self._playback_mode

    async def add_client(self, ws):
        async with self._clients_lock:
            self._clients.add(ws)
        logger.info("Client connected, total: %d", len(self._clients))

    async def remove_client(self, ws):
        async with self._clients_lock:
            self._clients.discard(ws)
        logger.info("Client disconnected, total: %d", len(self._clients))

    async def start(self):
        """Start the full pipeline: BladeRF -> DSP -> WebSocket broadcast."""
        if self._streaming:
            logger.warning("Already streaming")
            return False

        # Create queues
        self._iq_queue = queue.Queue(maxsize=self._config.iq_queue_size)
        self._result_queue = asyncio.Queue(maxsize=self._config.result_queue_size)

        # Configure BladeRF chunk size to match FFT size
        self._bladerf.set_chunk_size(self._config.dsp.fft_size)

        # Start BladeRF (GNU Radio thread)
        if not self._bladerf.start(self._iq_queue):
            logger.error("Failed to start BladeRF")
            return False

        # Start DSP thread
        self._dsp_running.set()
        self._dsp_thread = threading.Thread(
            target=self._dsp_loop,
            name="dsp-thread",
            daemon=True,
        )
        self._dsp_thread.start()

        # Start async broadcast loop
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

        self._streaming = True
        logger.info("Streaming pipeline started")
        return True

    async def stop(self):
        """Stop all pipeline components in correct order."""
        if not self._streaming:
            return

        self._streaming = False
        logger.info("Stopping streaming pipeline...")

        # 1. Signal DSP thread to stop
        self._dsp_running.clear()

        # 2. Stop BladeRF first (starves the queue naturally)
        self._bladerf.stop()

        # 3. Put sentinel to unblock DSP thread if waiting on queue.get()
        if self._iq_queue:
            try:
                self._iq_queue.put_nowait(None)
            except queue.Full:
                pass

        # 3. Join DSP thread
        if self._dsp_thread and self._dsp_thread.is_alive():
            self._dsp_thread.join(timeout=5.0)
            if self._dsp_thread.is_alive():
                logger.warning("DSP thread did not exit in 5s")

        # 4. Cancel broadcast task
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

        # 5. Drain queues
        if self._iq_queue:
            while not self._iq_queue.empty():
                try:
                    self._iq_queue.get_nowait()
                except queue.Empty:
                    break

        # 6. Reset DSP state
        self._dsp.reset()

        logger.info("Streaming pipeline stopped")

    async def pause(self):
        """
        Pause DSP processing and broadcast, but keep flowgraph running
        and WebSocket clients connected. Used by sweep engine.
        """
        if not self._streaming or self._paused:
            return

        logger.info("Pausing live DSP pipeline...")

        # Stop DSP thread
        self._dsp_running.clear()
        if self._dsp_thread and self._dsp_thread.is_alive():
            self._dsp_thread.join(timeout=5.0)

        self._paused = True
        logger.info("Live DSP pipeline paused")

    async def resume(self):
        """
        Resume DSP processing after a pause. Restarts the DSP thread
        and ensures the flowgraph is running.
        """
        if not self._paused:
            return

        logger.info("Resuming live DSP pipeline...")

        # Reset DSP state (clear stale averaging)
        self._dsp.reset()

        # Ensure we have a valid IQ queue
        if self._iq_queue is None:
            self._iq_queue = queue.Queue(maxsize=self._config.iq_queue_size)

        # Drain stale IQ data
        while not self._iq_queue.empty():
            try:
                self._iq_queue.get_nowait()
            except queue.Empty:
                break

        # Restart BladeRF if not running (sample rate may have changed)
        status = self._bladerf.get_status()
        if not status['running']:
            self._bladerf.set_chunk_size(self._config.dsp.fft_size)
            if not self._bladerf.start(self._iq_queue):
                logger.error("Failed to restart BladeRF after pause")
                self._paused = False
                self._streaming = False
                return

        # Restart DSP thread
        self._dsp_running.set()
        self._dsp_thread = threading.Thread(
            target=self._dsp_loop,
            name="dsp-thread",
            daemon=True,
        )
        self._dsp_thread.start()

        # Ensure broadcast loop is running
        if self._broadcast_task is None or self._broadcast_task.done():
            self._result_queue = asyncio.Queue(maxsize=self._config.result_queue_size)
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

        self._paused = False
        logger.info("Live DSP pipeline resumed")

    async def ensure_broadcast_pipeline(self):
        """
        Ensure the result queue and broadcast task exist.

        Called by sweep engine before injecting packets, so that sweep
        data can reach WebSocket clients even when live streaming was
        never started.
        """
        self._sweep_active = True

        if self._result_queue is None:
            self._result_queue = asyncio.Queue(maxsize=self._config.result_queue_size)

        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    def end_sweep_broadcast(self):
        """Clear sweep-active flag. Broadcast loop will exit if not streaming."""
        self._sweep_active = False

    def inject_packet(self, packet_bytes):
        """
        Allow external components (sweep engine) to send binary packets
        through the WebSocket broadcast pipeline.
        """
        if self._result_queue is None:
            return

        try:
            self._loop.call_soon_threadsafe(
                self._result_queue.put_nowait, packet_bytes
            )
        except (asyncio.QueueFull, RuntimeError):
            pass  # Drop if queue full or loop closed

    def _get_current_status(self):
        """Get hardware status from BladeRF or playback metadata."""
        if self._playback_mode and self._recording_manager:
            pb = self._recording_manager.playback
            state = pb.get_status()
            return {
                'center_freq': state['playback_center_freq'],
                'sample_rate': state['playback_sample_rate'],
                'bandwidth': state['playback_sample_rate'],
                'gain': 0.0,
                'running': state['playback_active'],
            }
        return self._bladerf.get_status()

    async def start_playback(self, filename):
        """
        Start playback mode: stop live streaming, feed IQ from file.

        Returns metadata dict or None on failure.
        """
        if not self._recording_manager:
            return None

        rm = self._recording_manager

        # Stop live streaming if active
        if self._streaming:
            await self.stop()

        # Create queues
        self._iq_queue = queue.Queue(maxsize=self._config.iq_queue_size)
        self._result_queue = asyncio.Queue(maxsize=self._config.result_queue_size)

        # Start playback (feeds iq_queue)
        metadata = rm.playback.start(
            filename, self._iq_queue, self._config.dsp.fft_size
        )
        if not metadata:
            return None

        # Reset DSP state
        self._dsp.reset()

        # Start DSP thread (reads from iq_queue, same as live)
        self._dsp_running.set()
        self._dsp_thread = threading.Thread(
            target=self._dsp_loop,
            name="dsp-thread",
            daemon=True,
        )
        self._dsp_thread.start()

        # Start broadcast loop
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

        self._streaming = True
        self._playback_mode = True
        logger.info("Playback mode started: %s", filename)
        return metadata

    async def stop_playback(self):
        """Stop playback and return to idle state."""
        if not self._playback_mode:
            return

        if self._recording_manager:
            self._recording_manager.playback.stop()

        # Stop DSP thread
        self._dsp_running.clear()
        if self._dsp_thread and self._dsp_thread.is_alive():
            self._dsp_thread.join(timeout=5.0)

        # Cancel broadcast
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

        self._streaming = False
        self._playback_mode = False
        self._dsp.reset()
        logger.info("Playback mode stopped")

    def _bridge_signal_events(self, events):
        """Bridge signal detection events from DSP thread to asyncio clients."""
        for event in events:
            sig = event.signal
            msg = json.dumps({
                'type': 'signal_event',
                'data': {
                    'event': event.event_type,
                    'signal_id': sig.signal_id,
                    'center_freq': sig.center_freq,
                    'peak_freq': sig.peak_freq,
                    'bandwidth': sig.bandwidth,
                    'peak_power': sig.peak_power,
                    'avg_power': sig.avg_power,
                    'hit_count': sig.hit_count,
                    'classification': sig.classification,
                },
            })

            # Persist to database (offload to asyncio thread to avoid blocking DSP)
            if self._signal_db:
                db = self._signal_db
                if event.event_type in ('signal_new', 'signal_update'):
                    self._loop.call_soon_threadsafe(
                        db.upsert_signal,
                        sig.center_freq,
                        sig.peak_freq,
                        sig.bandwidth,
                        sig.peak_power,
                        sig.avg_power,
                        1,
                    )
                elif event.event_type == 'signal_lost':
                    self._loop.call_soon_threadsafe(
                        db.mark_lost,
                        sig.center_freq,
                    )

            # Send to all clients via asyncio
            try:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._send_text_to_clients(msg),
                )
            except RuntimeError:
                pass

    async def _send_text_to_clients(self, text):
        """Send a JSON text frame to all connected clients."""
        async with self._clients_lock:
            disconnected = []
            for ws in self._clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                self._clients.discard(ws)

    def _dsp_loop(self):
        """
        DSP processing thread.

        Reads IQ chunks from iq_queue, processes through DSP pipeline,
        and pushes binary packets into the asyncio result_queue.
        """
        logger.info("DSP thread started")
        frame_interval = 1.0 / self._config.target_fps
        last_emit = 0.0
        frame_count = 0
        error_count = 0

        while self._dsp_running.is_set():
            try:
                # Block waiting for IQ data (1s timeout to check running flag)
                try:
                    iq_chunk = self._iq_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Sentinel value signals shutdown
                if iq_chunk is None:
                    break

                # IQ recording tap: copy raw chunk to recorder before DSP
                if (self._recording_manager and
                        self._recording_manager.iq_recorder.is_recording):
                    self._recording_manager.iq_recorder.put(iq_chunk)

                # Process through DSP pipeline
                result = self._dsp.process(iq_chunk)
                if result is None:
                    continue

                # Frame rate limiting
                now = time.monotonic()
                if now - last_emit < frame_interval:
                    continue
                last_emit = now
                frame_count += 1

                # Get current status (BladeRF or playback metadata)
                status = self._get_current_status()

                # AGC update (live mode only)
                if not self._playback_mode and self._agc.enabled:
                    new_gain = self._agc.update(
                        result.peak_power, status['gain']
                    )
                    if new_gain is not None:
                        self._bladerf.set_gain(new_gain)
                        status = self._bladerf.get_status()

                # Spectrum recording tap (throttled internally to ~1 Hz)
                if (self._recording_manager and
                        self._recording_manager.spectrum_recorder.is_recording):
                    self._recording_manager.spectrum_recorder.capture(
                        result, status['center_freq'], status['sample_rate']
                    )

                # Signal detection (throttled internally)
                if self._detector and self._detector.enabled:
                    events = self._detector.detect(
                        result.spectrum,
                        result.noise_floor,
                        status['center_freq'],
                        status['sample_rate'],
                    )
                    if events:
                        self._bridge_signal_events(events)

                # Build binary packet
                packet = encode_spectrum_packet(
                    spectrum=result.spectrum,
                    center_freq=status['center_freq'],
                    sample_rate=status['sample_rate'],
                    bandwidth=status['bandwidth'],
                    gain=status['gain'],
                    fft_size=self._config.dsp.fft_size,
                    noise_floor=result.noise_floor,
                    peak_power=result.peak_power,
                    peak_freq_offset=result.peak_freq_offset,
                    peak_hold=result.peak_hold,
                )

                # Bridge to asyncio: put result in asyncio queue
                try:
                    self._loop.call_soon_threadsafe(
                        self._result_queue.put_nowait, packet
                    )
                except (asyncio.QueueFull, RuntimeError):
                    pass  # Drop frame if queue full or loop closed

                # Reset error count on success
                error_count = 0

                # Periodic stats
                if frame_count % 600 == 0:  # Every ~10 seconds at 60fps
                    logger.info(
                        "DSP stats: %d frames emitted, IQ queue: %d/%d",
                        frame_count,
                        self._iq_queue.qsize(),
                        self._config.iq_queue_size,
                    )

            except Exception as e:
                error_count += 1
                logger.error("DSP error (%d): %s", error_count, e, exc_info=True)
                if error_count > 10:
                    logger.critical("Too many DSP errors, stopping")
                    self._dsp_running.clear()
                    break
                time.sleep(0.1)

        logger.info("DSP thread exited (processed %d frames)", frame_count)

    async def _broadcast_loop(self):
        """
        Async task that reads from result_queue and sends to all clients.
        Stays alive during sweep mode (paused state) to deliver sweep packets.
        """
        logger.info("Broadcast loop started")

        while (self._streaming or self._paused or self._sweep_active
               or self._playback_mode):
            try:
                packet = await asyncio.wait_for(
                    self._result_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Drain queue to always send latest — but only for live spectrum.
            # Sweep segments represent different frequency bands; dropping any
            # causes gaps in the panorama display.
            latest = packet
            if not self._sweep_active:
                while not self._result_queue.empty():
                    try:
                        latest = self._result_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

            # Send to all connected clients
            async with self._clients_lock:
                disconnected = []
                for ws in self._clients:
                    try:
                        await ws.send_bytes(latest)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    self._clients.discard(ws)
                    logger.info("Removed disconnected client")

        logger.info("Broadcast loop exited")
