"""
WebSocket endpoint for real-time spectrum data.

Uses native FastAPI WebSocket (binary frames, no Socket.IO overhead).
Commands come in as JSON text frames, spectrum data goes out as binary frames.
"""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


def create_ws_router():
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        app = ws.app
        manager = app.state.stream_manager
        bladerf = app.state.bladerf
        config = app.state.config

        await manager.add_client(ws)

        # Send initial full status (hardware + DSP + AGC)
        status = _build_full_status(bladerf, app.state.dsp, manager, config)
        await _send_status(ws, status)

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                cmd = msg.get('cmd')

                if cmd == 'start':
                    ok = await manager.start()
                    status = _build_full_status(bladerf, app.state.dsp, manager, config)
                    status['streaming'] = ok
                    await _send_status(ws, status)

                elif cmd == 'stop':
                    await manager.stop()
                    status = _build_full_status(bladerf, app.state.dsp, manager, config)
                    status['streaming'] = False
                    await _send_status(ws, status)

                elif cmd == 'set_frequency':
                    freq = float(msg['value'])
                    ok = bladerf.set_frequency(freq)
                    await _send_status(ws, {
                        'center_freq': freq, 'ok': ok,
                    })

                elif cmd == 'set_gain':
                    gain = float(msg['value'])
                    ok = bladerf.set_gain(gain)
                    await _send_status(ws, {'gain': gain, 'ok': ok})

                elif cmd == 'set_sample_rate':
                    rate = float(msg['value'])
                    ok = bladerf.set_sample_rate(rate)
                    await _send_status(ws, {
                        'sample_rate': rate, 'ok': ok,
                    })

                elif cmd == 'set_bandwidth':
                    bw = float(msg['value'])
                    ok = bladerf.set_bandwidth(bw)
                    await _send_status(ws, {
                        'bandwidth': bw, 'ok': ok,
                    })

                elif cmd == 'set_fft_size':
                    size = int(msg['value'])
                    if manager.is_streaming:
                        await _send_error(ws, 'Stop streaming before changing FFT size')
                    else:
                        config.dsp.fft_size = size
                        # Reinitialize DSP pipeline with new FFT size
                        from dsp.pipeline import DSPPipeline
                        app.state.dsp = DSPPipeline(config.dsp)
                        manager._dsp = app.state.dsp
                        await _send_status(ws, {
                            'fft_size': size, 'ok': True,
                        })

                elif cmd == 'set_dsp':
                    dsp = app.state.dsp
                    for key, value in msg.get('params', {}).items():
                        dsp.set_param(key, value)
                    await _send_status(ws, {'dsp_updated': True})

                elif cmd == 'set_agc':
                    agc = manager.agc
                    if 'enabled' in msg:
                        agc.enabled = bool(msg['enabled'])
                    for key in ('target_dbfs', 'hysteresis', 'gain_step', 'min_interval'):
                        if key in msg:
                            agc.set_param(key, msg[key])
                    await _send_status(ws, {
                        'agc_enabled': agc.enabled, 'ok': True,
                    })

                elif cmd == 'get_status':
                    status = _build_full_status(bladerf, app.state.dsp, manager, config)
                    await _send_status(ws, status)

                elif cmd == 'check_device':
                    from hardware.probe import probe_bladerf_devices
                    result = probe_bladerf_devices()
                    await _send_status(ws, {
                        'device_connected': result['available'],
                        'device_info': result['devices'][0]['info'] if result['devices'] else None,
                        'device_error': result['error'],
                    })

                else:
                    logger.warning("Unknown command: %s", cmd)

        except WebSocketDisconnect:
            logger.info("Client disconnected normally")
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON from client: %s", e)
        except Exception:
            logger.error("WebSocket error", exc_info=True)
        finally:
            await manager.remove_client(ws)

    return router


def _build_full_status(bladerf, dsp, manager, config):
    """Build a complete status dict with hardware, DSP, and AGC params."""
    status = bladerf.get_status()
    status['streaming'] = manager.is_streaming
    status['fft_size'] = config.dsp.fft_size
    status.update(dsp.get_params())
    status['agc_enabled'] = manager.agc.enabled
    return status


async def _send_status(ws, data):
    """Send a JSON status message."""
    await ws.send_text(json.dumps({'type': 'status', 'data': data}))


async def _send_error(ws, message):
    """Send a JSON error message."""
    await ws.send_text(json.dumps({'type': 'error', 'message': message}))
