#!/usr/bin/env python3
"""
Spectrum Analyzer v2.0 - Main Entry Point

FastAPI + uvicorn, no monkey-patching, proper thread isolation.
"""

import argparse
import logging
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from logging_config import setup_logging


def main():
    parser = argparse.ArgumentParser(description='Spectrum Analyzer v2')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='Server port (default: 5000)')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='Server host (default: 0.0.0.0)')
    parser.add_argument('--sample-rate', type=float, default=2e6,
                        help='Sample rate in Hz (default: 2e6)')
    parser.add_argument('--fft-size', type=int, default=2048,
                        help='FFT size (default: 2048)')
    args = parser.parse_args()

    # Setup logging
    console_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(console_level=console_level)

    logger = logging.getLogger(__name__)

    # Build config
    config = Config(
        debug=args.debug,
        host=args.host,
        port=args.port,
    )
    config.bladerf.sample_rate = args.sample_rate
    config.dsp.fft_size = args.fft_size

    logger.info("Starting Spectrum Analyzer v2.0")
    logger.info("  Host: %s:%d", config.host, config.port)
    logger.info("  Debug: %s", config.debug)

    # Import uvicorn here to avoid import issues
    import uvicorn

    # Create app
    from app import create_app
    app = create_app(config)

    # Run with uvicorn
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level='info' if not config.debug else 'debug',
        ws='websockets',
        timeout_keep_alive=30,
    )


if __name__ == '__main__':
    main()
