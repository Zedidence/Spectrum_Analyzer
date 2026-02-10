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

    @property
    def is_streaming(self):
        return self._streaming

    @property
    def agc(self):
        return self._agc

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

        # 1. Stop DSP thread
        self._dsp_running.clear()

        # 2. Stop BladeRF (unblocks DSP thread if waiting on iq_queue)
        self._bladerf.stop()

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

                # AGC update
                status = self._bladerf.get_status()
                if self._agc.enabled:
                    new_gain = self._agc.update(
                        result.peak_power, status['gain']
                    )
                    if new_gain is not None:
                        self._bladerf.set_gain(new_gain)
                        status = self._bladerf.get_status()

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
        """
        logger.info("Broadcast loop started")

        while self._streaming:
            try:
                packet = await asyncio.wait_for(
                    self._result_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Drain queue to always send latest
            latest = packet
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
