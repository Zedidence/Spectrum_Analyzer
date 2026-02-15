"""
REST API routes for non-realtime operations.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse as FastAPIFileResponse
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
        manager = request.app.state.stream_manager
        bladerf = request.app.state.bladerf

        # If device is already in use, report status from the existing handle
        if manager.is_streaming:
            status = bladerf.get_status()
            return {
                'connected': True,
                'device_info': f"BladeRF active at {status['center_freq']/1e6:.3f} MHz",
                'error': None,
                'streaming': True,
            }

        result = probe_bladerf_devices()
        return {
            'connected': result['available'],
            'device_info': result['devices'][0]['info'] if result['devices'] else None,
            'error': result['error'],
            'streaming': False,
        }

    @router.post("/reconnect")
    async def reconnect_device(request: Request):
        manager = request.app.state.stream_manager
        bladerf = request.app.state.bladerf
        config = request.app.state.config

        if manager.is_streaming:
            await manager.stop()

        bladerf.cleanup()
        probe = probe_bladerf_devices()

        if probe['available']:
            # Reinitialize the BladeRF interface with current config
            from hardware.bladerf_interface import BladeRFInterface
            new_bladerf = BladeRFInterface(config.bladerf)
            request.app.state.bladerf = new_bladerf
            # Update manager's reference
            manager._bladerf = new_bladerf

        return {
            'success': probe['available'],
            'message': probe['devices'][0]['info'] if probe['devices'] else (probe['error'] or 'Unknown error'),
        }

    # --- Recording endpoints ---

    @router.get("/recordings")
    async def list_recordings(request: Request):
        rm = getattr(request.app.state, 'recording_manager', None)
        if not rm:
            return {'recordings': [], 'error': 'Not initialized'}
        return {
            'recordings': rm.list_recordings(),
            'storage': rm.get_storage_info(),
        }

    @router.get("/recordings/{filename}")
    async def download_recording(filename: str, request: Request):
        rm = getattr(request.app.state, 'recording_manager', None)
        if not rm:
            return {'error': 'Not initialized'}

        # Sanitize filename (prevent path traversal)
        safe_name = Path(filename).name
        storage = Path(rm._config.storage_path)

        for ext in ('.raw', '.csv'):
            path = storage / f"{safe_name}{ext}"
            if path.exists():
                return FastAPIFileResponse(
                    path=str(path),
                    filename=f"{safe_name}{ext}",
                    media_type='application/octet-stream',
                )

        return {'error': 'Recording not found'}

    @router.delete("/recordings/{filename}")
    async def delete_recording(filename: str, request: Request):
        rm = getattr(request.app.state, 'recording_manager', None)
        if not rm:
            return {'error': 'Not initialized'}

        safe_name = Path(filename).name
        ok = rm.delete_recording(safe_name)
        return {'ok': ok}

    return router
