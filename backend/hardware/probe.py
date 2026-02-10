"""
BladeRF device probing.

Multi-method detection: bladeRF-cli, osmosdr, USB lsusb.
Extracted from the original bladerf_interface.py.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


def probe_bladerf_devices():
    """
    Probe for available BladeRF devices using multiple methods.

    Returns:
        dict: {
            'available': bool,
            'devices': list of device info dicts,
            'error': str or None
        }
    """
    result = {
        'available': False,
        'devices': [],
        'error': None,
    }

    try:
        # Method 1: bladeRF-cli
        try:
            proc = subprocess.run(
                ['bladeRF-cli', '-p'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = proc.stdout + proc.stderr

            if 'Serial' in output or 'bladerf' in output.lower():
                lines = output.strip().split('\n')
                for line in lines:
                    if 'Serial' in line or 'bladerf' in line.lower():
                        result['devices'].append({'info': line.strip()})
                        result['available'] = True
            elif 'No bladeRF' in output or 'not found' in output.lower():
                result['error'] = 'No BladeRF devices found'
            elif proc.returncode == 0:
                result['devices'].append({'info': 'BladeRF detected (bladeRF-cli)'})
                result['available'] = True

        except FileNotFoundError:
            logger.debug("bladeRF-cli not found, trying osmosdr probe")
        except subprocess.TimeoutExpired:
            logger.warning("bladeRF-cli timed out")

        # Method 2: osmosdr probe
        if not result['available'] and not result['error']:
            try:
                from osmosdr import source
                test_source = source("bladerf=0")
                result['available'] = True
                result['devices'].append({
                    'info': 'BladeRF detected via osmosdr',
                    'device_string': 'bladerf=0',
                })
                del test_source
            except Exception as e:
                error_str = str(e).lower()
                if 'not found' in error_str or 'no device' in error_str:
                    result['error'] = 'No BladeRF device found - check USB connection'
                elif 'permission' in error_str:
                    result['error'] = 'Permission denied - check udev rules'
                elif 'busy' in error_str or 'in use' in error_str:
                    result['error'] = 'BladeRF is busy - another application may be using it'
                else:
                    result['error'] = f'BladeRF error: {e}'

        # Method 3: USB fallback
        if not result['available'] and not result['error']:
            try:
                proc = subprocess.run(
                    ['lsusb'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # BladeRF USB IDs: 2cf0:5246 (x40/x115), 2cf0:5250 (2.0 micro)
                if '2cf0:5246' in proc.stdout or '2cf0:5250' in proc.stdout:
                    result['available'] = True
                    result['devices'].append({
                        'info': 'BladeRF detected via USB (may need driver)',
                        'usb': True,
                    })
                else:
                    result['error'] = 'No BladeRF USB device found'
            except Exception:
                pass

    except Exception as e:
        result['error'] = f'Probe failed: {e}'
        logger.error("Device probe failed: %s", e, exc_info=True)

    return result
