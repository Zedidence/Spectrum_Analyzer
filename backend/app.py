"""
FastAPI application factory.

No eventlet, no monkey-patching. Pure asyncio + native threads.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import Config
from hardware.bladerf_interface import BladeRFInterface
from dsp.pipeline import DSPPipeline
from streaming.manager import StreamManager
from sweep.engine import SweepEngine
from detection.detector import SignalDetector
from detection.database import SignalDatabase
from recording.manager import RecordingManager
from api.routes import create_router
from api.websocket import create_ws_router

logger = logging.getLogger(__name__)

# Resolve paths relative to this file
BACKEND_DIR = Path(__file__).parent
STATIC_DIR = BACKEND_DIR.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    config = app.state.config

    logger.info("=" * 60)
    logger.info("Spectrum Analyzer v2.0 starting")
    logger.info("  FastAPI + uvicorn (no eventlet)")
    logger.info("  FFT size: %d", config.dsp.fft_size)
    logger.info("  Sample rate: %.2f MS/s", config.bladerf.sample_rate / 1e6)
    logger.info("  Target FPS: %d", config.target_fps)
    logger.info("=" * 60)

    # Initialize hardware interface (does NOT start streaming)
    bladerf = BladeRFInterface(config.bladerf)
    app.state.bladerf = bladerf

    # Initialize DSP pipeline
    dsp = DSPPipeline(config.dsp)
    app.state.dsp = dsp

    # Initialize stream manager
    loop = asyncio.get_running_loop()
    manager = StreamManager(
        bladerf=bladerf,
        dsp=dsp,
        config=config,
        loop=loop,
    )
    app.state.stream_manager = manager

    # Initialize sweep engine
    sweep_engine = SweepEngine(
        bladerf=bladerf,
        config=config,
        loop=loop,
        stream_manager=manager,
    )
    app.state.sweep_engine = sweep_engine

    # Initialize signal detection
    signal_db = SignalDatabase(
        db_path=str(BACKEND_DIR.parent / "data" / "signals.db"),
    )
    app.state.signal_db = signal_db

    detector = SignalDetector(config.detection)
    manager.set_detector(detector, signal_db)
    app.state.detector = detector

    # Initialize recording manager
    recording_manager = RecordingManager(config.recording)
    manager.set_recording_manager(recording_manager)
    app.state.recording_manager = recording_manager

    logger.info("Application initialized, ready for connections")

    yield

    # Shutdown
    logger.info("Shutting down...")
    recording_manager.stop_all()
    await sweep_engine.stop()
    await manager.stop()
    bladerf.cleanup()
    logger.info("Shutdown complete")


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching static files during development."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Spectrum Analyzer",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.config = config

    # Prevent browser caching of static files
    app.add_middleware(NoCacheStaticMiddleware)

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # API routes
    app.include_router(create_router(), prefix="/api")

    # WebSocket endpoint
    app.include_router(create_ws_router())

    # Serve index.html at root
    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app
