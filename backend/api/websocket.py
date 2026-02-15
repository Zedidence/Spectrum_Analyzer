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

        sweep_engine = app.state.sweep_engine

        rec_manager = getattr(app.state, 'recording_manager', None)

        await manager.add_client(ws)

        # Send initial full status (hardware + DSP + AGC + sweep + recording)
        status = _build_full_status(bladerf, app.state.dsp, manager, config,
                                    sweep_engine, rec_manager)
        await _send_status(ws, status)

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                cmd = msg.get('cmd')

                if cmd == 'start':
                    ok = await manager.start()
                    status = _build_full_status(bladerf, app.state.dsp, manager, config,
                                    sweep_engine, rec_manager)
                    status['streaming'] = ok
                    await _send_status(ws, status)

                elif cmd == 'stop':
                    await manager.stop()
                    status = _build_full_status(bladerf, app.state.dsp, manager, config,
                                    sweep_engine, rec_manager)
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
                        new_dsp = DSPPipeline(config.dsp)
                        app.state.dsp = new_dsp
                        manager.set_dsp(new_dsp)
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
                    status = _build_full_status(bladerf, app.state.dsp, manager, config,
                                    sweep_engine, rec_manager)
                    await _send_status(ws, status)

                elif cmd == 'check_device':
                    from hardware.probe import probe_bladerf_devices
                    result = probe_bladerf_devices()
                    await _send_status(ws, {
                        'device_connected': result['available'],
                        'device_info': result['devices'][0]['info'] if result['devices'] else None,
                        'device_error': result['error'],
                    })

                # --- Sweep commands ---

                elif cmd == 'sweep_start':
                    from config import SweepConfig
                    sweep_engine = app.state.sweep_engine
                    mode = msg.get('mode', 'survey')
                    freq_start = float(msg.get('freq_start', 47e6))
                    freq_end = float(msg.get('freq_end', 6e9))
                    fft_size = int(msg.get('fft_size', 2048))
                    sweep_sr = float(msg.get('sample_rate', 20e6))
                    averages = int(msg.get('averages', 4))

                    # Validate sweep parameters
                    if freq_start >= freq_end:
                        await _send_error(ws, 'freq_start must be less than freq_end')
                        continue
                    if fft_size <= 0 or (fft_size & (fft_size - 1)) != 0:
                        await _send_error(ws, 'fft_size must be a positive power of 2')
                        continue
                    if sweep_sr <= 0:
                        await _send_error(ws, 'sample_rate must be positive')
                        continue
                    if averages <= 0:
                        await _send_error(ws, 'averages must be positive')
                        continue

                    sweep_config = SweepConfig(
                        mode=mode,
                        freq_start=freq_start,
                        freq_end=freq_end,
                        sweep_sample_rate=sweep_sr,
                        fft_size=fft_size,
                        averages_per_step=averages,
                        settle_chunks=int(msg.get('settle_chunks', 10)),
                        display_bins=int(msg.get('display_bins', 4096)),
                        continuous=(mode == 'band_monitor'),
                    )
                    ok = await sweep_engine.start(sweep_config)
                    status = sweep_engine.get_status()
                    status['ok'] = ok
                    await _send_status(ws, status)

                elif cmd == 'sweep_stop':
                    sweep_engine = app.state.sweep_engine
                    await sweep_engine.stop()
                    await _send_status(ws, sweep_engine.get_status())

                elif cmd == 'sweep_status':
                    sweep_engine = app.state.sweep_engine
                    await _send_status(ws, sweep_engine.get_status())

                # --- Detection commands ---

                elif cmd == 'detection_enable':
                    detector = manager.detector
                    if detector:
                        detector.enabled = bool(msg.get('enabled', True))
                        await _send_status(ws, detector.get_status())
                    else:
                        await _send_error(ws, 'Detector not initialized')

                elif cmd == 'detection_set':
                    detector = manager.detector
                    if detector:
                        for key, value in msg.get('params', {}).items():
                            detector.set_param(key, value)
                        await _send_status(ws, detector.get_status())

                elif cmd == 'detection_status':
                    detector = manager.detector
                    if detector:
                        status = detector.get_status()
                        status['signals'] = [
                            {
                                'signal_id': s.signal_id,
                                'center_freq': s.center_freq,
                                'peak_freq': s.peak_freq,
                                'bandwidth': s.bandwidth,
                                'peak_power': s.peak_power,
                                'avg_power': s.avg_power,
                                'hit_count': s.hit_count,
                                'classification': s.classification,
                            }
                            for s in detector.get_tracked_signals()
                        ]
                        await _send_status(ws, status)

                elif cmd == 'signal_list':
                    signal_db = getattr(app.state, 'signal_db', None)
                    if signal_db:
                        signals = signal_db.get_signals(
                            active_only=msg.get('active_only', False),
                            limit=msg.get('limit', 100),
                            freq_min=msg.get('freq_min'),
                            freq_max=msg.get('freq_max'),
                        )
                        await _send_status(ws, {'signal_list': signals})
                    else:
                        await _send_error(ws, 'Signal database not available')

                elif cmd == 'signal_classify':
                    signal_db = getattr(app.state, 'signal_db', None)
                    if signal_db:
                        ok = signal_db.classify_signal(
                            int(msg['signal_id']),
                            msg.get('classification', ''),
                            msg.get('notes', ''),
                        )
                        await _send_status(ws, {'ok': ok})

                elif cmd == 'signal_delete':
                    signal_db = getattr(app.state, 'signal_db', None)
                    if signal_db:
                        ok = signal_db.delete_signal(int(msg['signal_id']))
                        await _send_status(ws, {'ok': ok})

                elif cmd == 'signal_db_stats':
                    signal_db = getattr(app.state, 'signal_db', None)
                    if signal_db:
                        await _send_status(ws, signal_db.get_stats())

                # --- Recording commands ---

                elif cmd == 'rec_iq_start':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        hw_status = bladerf.get_status()
                        filename = rm.iq_recorder.start(
                            sample_rate=hw_status['sample_rate'],
                            center_freq=hw_status['center_freq'],
                            bandwidth=hw_status['bandwidth'],
                            gain=hw_status['gain'],
                            fft_size=config.dsp.fft_size,
                        )
                        if filename:
                            await _send_status(ws, {
                                'ok': True, 'iq_recording': True,
                                'iq_filename': filename,
                            })
                        else:
                            await _send_error(ws, 'Failed to start IQ recording')
                    else:
                        await _send_error(ws, 'Recording manager not initialized')

                elif cmd == 'rec_iq_stop':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        filename = rm.iq_recorder.stop()
                        await _send_status(ws, {
                            'ok': True, 'iq_recording': False,
                            'iq_filename': filename,
                        })

                elif cmd == 'rec_spectrum_start':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        hw_status = bladerf.get_status()
                        filename = rm.spectrum_recorder.start(
                            sample_rate=hw_status['sample_rate'],
                            center_freq=hw_status['center_freq'],
                            fft_size=config.dsp.fft_size,
                        )
                        if filename:
                            await _send_status(ws, {
                                'ok': True, 'spectrum_recording': True,
                                'spectrum_filename': filename,
                            })
                        else:
                            await _send_error(ws, 'Failed to start spectrum recording')

                elif cmd == 'rec_spectrum_stop':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.spectrum_recorder.stop()
                        await _send_status(ws, {
                            'ok': True, 'spectrum_recording': False,
                        })

                elif cmd == 'rec_list':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        recordings = rm.list_recordings()
                        storage = rm.get_storage_info()
                        await _send_status(ws, {
                            'recordings': recordings,
                            'storage': storage,
                        })

                elif cmd == 'rec_delete':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        from pathlib import Path as _Path
                        safe_name = _Path(msg['filename']).name
                        ok = rm.delete_recording(safe_name)
                        await _send_status(ws, {'ok': ok})

                elif cmd == 'rec_status':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        await _send_status(ws, rm.get_status())

                # --- Playback commands ---

                elif cmd == 'playback_start':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        metadata = await manager.start_playback(msg['filename'])
                        if metadata:
                            await _send_status(ws, {
                                'ok': True,
                                'playback_active': True,
                                **rm.playback.get_status(),
                            })
                        else:
                            await _send_error(ws, 'Failed to start playback')

                elif cmd == 'playback_stop':
                    await manager.stop_playback()
                    await _send_status(ws, {
                        'ok': True, 'playback_active': False,
                    })

                elif cmd == 'playback_pause':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.playback.pause()
                        await _send_status(ws, rm.playback.get_status())

                elif cmd == 'playback_resume':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.playback.resume()
                        await _send_status(ws, rm.playback.get_status())

                elif cmd == 'playback_speed':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.playback.set_speed(float(msg['value']))
                        await _send_status(ws, rm.playback.get_status())

                elif cmd == 'playback_loop':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.playback.set_loop(bool(msg.get('enabled', True)))
                        await _send_status(ws, rm.playback.get_status())

                elif cmd == 'playback_seek':
                    rm = getattr(app.state, 'recording_manager', None)
                    if rm:
                        rm.playback.seek(float(msg['position']))
                        await _send_status(ws, rm.playback.get_status())

                else:
                    logger.warning("Unknown command: %s", cmd)

        except WebSocketDisconnect:
            logger.info("Client disconnected normally")
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON from client: %s", e)
            continue
        except Exception:
            logger.error("WebSocket error", exc_info=True)
        finally:
            await manager.remove_client(ws)

    return router


def _build_full_status(bladerf, dsp, manager, config, sweep_engine=None,
                       recording_manager=None):
    """Build a complete status dict with hardware, DSP, AGC, sweep, detection, and recording params."""
    status = bladerf.get_status()
    status['streaming'] = manager.is_streaming
    status['fft_size'] = config.dsp.fft_size
    status['playback_mode'] = manager.playback_mode
    status.update(dsp.get_params())
    status['agc_enabled'] = manager.agc.enabled
    if sweep_engine:
        status.update(sweep_engine.get_status())
    if manager.detector:
        status.update(manager.detector.get_status())
    if recording_manager:
        status.update(recording_manager.get_status())
    return status


async def _send_status(ws, data):
    """Send a JSON status message."""
    await ws.send_text(json.dumps({'type': 'status', 'data': data}))


async def _send_error(ws, message):
    """Send a JSON error message."""
    await ws.send_text(json.dumps({'type': 'error', 'message': message}))
