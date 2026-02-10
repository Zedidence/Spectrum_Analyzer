"""
REST API routes for non-realtime operations.
"""

import logging
from fastapi import APIRouter, Request
from hardware.probe import probe_bladerf_devices

logger = logging.getLogger(__name__)


def create_router():
    router = APIRouter()

    @router.get("/status")
    async def get_status(request: Request):
        bladerf = request.app.state.bladerf
        manager = request.app.state.stream_manager
        status = bladerf.get_status()
        status['streaming'] = manager.is_streaming
        status['fft_size'] = request.app.state.config.dsp.fft_size
        return status

    @router.get("/check_device")
    async def check_device(request: Request):
        result = probe_bladerf_devices()
        return {
            'connected': result['available'],
            'device_info': result['devices'][0]['info'] if result['devices'] else None,
            'error': result['error'],
            'streaming': request.app.state.stream_manager.is_streaming,
        }

    @router.post("/reconnect")
    async def reconnect_device(request: Request):
        manager = request.app.state.stream_manager
        bladerf = request.app.state.bladerf

        if manager.is_streaming:
            await manager.stop()

        bladerf.cleanup()
        probe = probe_bladerf_devices()

        return {
            'success': probe['available'],
            'message': probe['devices'][0]['info'] if probe['devices'] else (probe['error'] or 'Unknown error'),
        }

    return router
