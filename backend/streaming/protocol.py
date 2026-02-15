"""
Binary WebSocket protocol for spectrum data.

Frame format:
  Offset  Size  Type     Field
  0       1     uint8    version (0x02)
  1       1     uint8    message_type
  2       2     uint16   flags (big-endian)
  4       4     uint32   payload_length (big-endian)
  8       ...   payload  (varies by message_type)

Message types:
  0x01 = Spectrum data
  0x02 = Status update (JSON) -- sent as text frame instead
  0x03 = Sweep segment (incremental)
  0x04 = Sweep panorama (complete stitched result)

Flags:
  0x0001 = FLAG_PEAK_HOLD  (peak hold trace appended after spectrum)
  0x0002 = FLAG_SWEEP_COMPLETE  (last segment / complete panorama)
  0x0004 = FLAG_SWEEP_IN_PROGRESS  (sweep in progress)

Spectrum payload (type 0x01):
  Offset  Size       Type      Field
  0       8          float64   center_freq (Hz)
  8       8          float64   sample_rate (Hz)
  16      8          float64   bandwidth (Hz)
  24      4          float32   gain (dB)
  28      4          uint32    fft_size
  32      4          uint32    num_bins (display bins)
  36      4          float32   noise_floor (dB)
  40      4          float32   peak_power (dB)
  44      4          float32   peak_freq_offset (normalized)
  48      8          float64   timestamp (unix seconds)
  -- 56 bytes spectrum header --
  56      N*4        float32[] spectrum data (num_bins floats)
  -- if FLAG_PEAK_HOLD set --
  56+N*4  N*4        float32[] peak hold data (num_bins floats)
"""

import struct
import time
import numpy as np

VERSION = 0x02

# Message types
MSG_SPECTRUM = 0x01
MSG_SWEEP_SEGMENT = 0x03
MSG_SWEEP_PANORAMA = 0x04

# Flags
FLAG_NONE = 0x0000
FLAG_PEAK_HOLD = 0x0001
FLAG_SWEEP_COMPLETE = 0x0002
FLAG_SWEEP_IN_PROGRESS = 0x0004

# Frame header: version(B) + type(B) + flags(H) + payload_len(I) = 8 bytes
FRAME_HEADER_FMT = '!BBHI'
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FMT)

# Spectrum header within payload
SPECTRUM_HEADER_FMT = '!dddfIIfffd'
SPECTRUM_HEADER_SIZE = struct.calcsize(SPECTRUM_HEADER_FMT)


def encode_spectrum_packet(
    spectrum,
    center_freq,
    sample_rate,
    bandwidth,
    gain,
    fft_size,
    noise_floor=-100.0,
    peak_power=-100.0,
    peak_freq_offset=0.0,
    peak_hold=None,
):
    """
    Encode spectrum data into binary packet.

    Args:
        spectrum: float32 numpy array of power values
        center_freq: center frequency in Hz
        sample_rate: sample rate in Hz
        bandwidth: bandwidth in Hz
        gain: gain in dB
        fft_size: FFT size used
        noise_floor: estimated noise floor in dB
        peak_power: peak power in dB
        peak_freq_offset: normalized peak frequency offset
        peak_hold: optional float32 numpy array of peak hold values

    Returns:
        bytes: complete binary packet
    """
    num_bins = len(spectrum)
    flags = FLAG_NONE

    if peak_hold is not None:
        flags |= FLAG_PEAK_HOLD

    # Build spectrum header
    spectrum_header = struct.pack(
        SPECTRUM_HEADER_FMT,
        float(center_freq),
        float(sample_rate),
        float(bandwidth),
        float(gain),
        int(fft_size),
        int(num_bins),
        float(noise_floor),
        float(peak_power),
        float(peak_freq_offset),
        time.time(),
    )

    # Spectrum data as float32 bytes
    spectrum_bytes = spectrum.astype(np.float32).tobytes()
    payload = spectrum_header + spectrum_bytes

    # Append peak hold data if present
    if peak_hold is not None:
        payload += peak_hold.astype(np.float32).tobytes()

    # Frame header
    header = struct.pack(
        FRAME_HEADER_FMT,
        VERSION,
        MSG_SPECTRUM,
        flags,
        len(payload),
    )

    return header + payload


# Sweep segment header: sweep_id(I) + segment_idx(H) + total_segments(H) +
# freq_start(d) + freq_end(d) + sweep_start(d) + sweep_end(d) + num_bins(I)
SWEEP_SEGMENT_HEADER_FMT = '!IHHddddI'
SWEEP_SEGMENT_HEADER_SIZE = struct.calcsize(SWEEP_SEGMENT_HEADER_FMT)

# Sweep panorama header: sweep_id(I) + sweep_mode(B) + pad(3x) +
# freq_start(d) + freq_end(d) + num_bins(I) + sweep_time_ms(f) + timestamp(d)
SWEEP_PANORAMA_HEADER_FMT = '!IBxxxddIfd'
SWEEP_PANORAMA_HEADER_SIZE = struct.calcsize(SWEEP_PANORAMA_HEADER_FMT)


def encode_sweep_segment_packet(
    sweep_id,
    segment_idx,
    total_segments,
    freq_start,
    freq_end,
    sweep_start,
    sweep_end,
    spectrum,
):
    """
    Encode an incremental sweep segment into a binary packet.

    Sent during survey mode as each step completes, allowing the
    frontend to render sweep progress in real-time.
    """
    num_bins = len(spectrum)
    is_last = (segment_idx == total_segments - 1)
    flags = FLAG_SWEEP_COMPLETE if is_last else FLAG_SWEEP_IN_PROGRESS

    segment_header = struct.pack(
        SWEEP_SEGMENT_HEADER_FMT,
        int(sweep_id),
        int(segment_idx),
        int(total_segments),
        float(freq_start),
        float(freq_end),
        float(sweep_start),
        float(sweep_end),
        int(num_bins),
    )

    spectrum_bytes = spectrum.astype(np.float32).tobytes()
    payload = segment_header + spectrum_bytes

    header = struct.pack(
        FRAME_HEADER_FMT,
        VERSION,
        MSG_SWEEP_SEGMENT,
        flags,
        len(payload),
    )

    return header + payload


def encode_sweep_panorama_packet(
    sweep_id,
    sweep_mode,
    freq_start,
    freq_end,
    num_bins,
    sweep_time_ms,
    spectrum,
):
    """
    Encode a complete stitched panorama into a binary packet.

    Sent after a full sweep pass completes (survey) or on each
    completed loop (band monitor).
    """
    flags = FLAG_SWEEP_COMPLETE

    panorama_header = struct.pack(
        SWEEP_PANORAMA_HEADER_FMT,
        int(sweep_id),
        int(sweep_mode),
        float(freq_start),
        float(freq_end),
        int(num_bins),
        float(sweep_time_ms),
        time.time(),
    )

    spectrum_bytes = spectrum.astype(np.float32).tobytes()
    payload = panorama_header + spectrum_bytes

    header = struct.pack(
        FRAME_HEADER_FMT,
        VERSION,
        MSG_SWEEP_PANORAMA,
        flags,
        len(payload),
    )

    return header + payload
