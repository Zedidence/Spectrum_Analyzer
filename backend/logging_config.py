"""
Logging Configuration Module

Centralized logging setup with organized file output.

Log Directory Structure:
    logs/
    ├── app.log           # Main application log (INFO+)
    ├── error.log         # Errors only (ERROR+)
    ├── debug.log         # Detailed debug output (DEBUG+)
    ├── hardware/
    │   └── bladerf.log   # BladeRF hardware operations
    └── streaming/
        └── stream.log    # FFT streaming and processing

Usage:
    from logging_config import setup_logging, get_logger

    # Call once at startup
    setup_logging()

    # Get logger in any module
    logger = get_logger(__name__)
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime

# Base directory for logs (relative to backend/)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')

# Log format configurations
CONSOLE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
FILE_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# File size limits
MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
BACKUP_COUNT = 5  # Keep 5 backup files


def create_log_directories():
    """Create log directory structure."""
    directories = [
        LOG_DIR,
        os.path.join(LOG_DIR, 'hardware'),
        os.path.join(LOG_DIR, 'streaming'),
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)


def create_rotating_handler(filename, level=logging.DEBUG, max_bytes=MAX_BYTES, backup_count=BACKUP_COUNT):
    """
    Create a rotating file handler.

    Args:
        filename: Log file path (relative to LOG_DIR)
        level: Logging level
        max_bytes: Maximum file size before rotation
        backup_count: Number of backup files to keep

    Returns:
        RotatingFileHandler configured with formatter
    """
    filepath = os.path.join(LOG_DIR, filename)
    handler = RotatingFileHandler(
        filepath,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FILE_FORMAT, DATE_FORMAT))
    return handler


def create_console_handler(level=logging.INFO):
    """
    Create a console handler for stdout output.

    Args:
        level: Logging level

    Returns:
        StreamHandler configured with formatter
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT))
    return handler


def setup_logging(console_level=logging.INFO, file_level=logging.DEBUG):
    """
    Configure application-wide logging.

    Sets up:
    - Console output (INFO by default)
    - app.log: Main application log (INFO+)
    - error.log: Errors only (ERROR+)
    - debug.log: Full debug output (DEBUG+)
    - hardware/bladerf.log: Hardware operations
    - streaming/stream.log: FFT streaming

    Args:
        console_level: Logging level for console output
        file_level: Logging level for main log files
    """
    # Create directory structure
    create_log_directories()

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture all levels

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Add console handler
    root_logger.addHandler(create_console_handler(console_level))

    # Add main application log (INFO+)
    root_logger.addHandler(create_rotating_handler('app.log', logging.INFO))

    # Add error-only log (ERROR+)
    root_logger.addHandler(create_rotating_handler('error.log', logging.ERROR))

    # Add debug log (DEBUG+) - captures everything
    root_logger.addHandler(create_rotating_handler('debug.log', logging.DEBUG))

    # Configure specific loggers for different components
    setup_component_loggers()

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("=" * 70)
    logger.info("Logging initialized")
    logger.info(f"  Log directory: {os.path.abspath(LOG_DIR)}")
    logger.info(f"  Console level: {logging.getLevelName(console_level)}")
    logger.info(f"  File level: {logging.getLevelName(file_level)}")
    logger.info("=" * 70)


def setup_component_loggers():
    """Configure loggers for specific components with dedicated log files."""

    # Hardware loggers (v2 module paths)
    bladerf_handler = create_rotating_handler('hardware/bladerf.log', logging.DEBUG)
    logging.getLogger('hardware.bladerf_interface').addHandler(bladerf_handler)
    logging.getLogger('hardware.probe').addHandler(bladerf_handler)

    # DSP loggers
    logging.getLogger('dsp.pipeline').addHandler(bladerf_handler)
    logging.getLogger('dsp.dc_removal').addHandler(bladerf_handler)

    # Streaming/processing loggers
    stream_handler = create_rotating_handler('streaming/stream.log', logging.DEBUG)
    logging.getLogger('streaming.manager').addHandler(stream_handler)
    logging.getLogger('streaming.protocol').addHandler(stream_handler)
    logging.getLogger('api.websocket').addHandler(stream_handler)
    logging.getLogger('api.routes').addHandler(stream_handler)

    # Legacy module paths (for backward compat if old app.py is used)
    logging.getLogger('bladerf_interface').addHandler(bladerf_handler)
    logging.getLogger('signal_processor').addHandler(bladerf_handler)
    logging.getLogger('processing').addHandler(stream_handler)
    logging.getLogger('socketio_handlers').addHandler(stream_handler)

    # Reduce verbosity of third-party loggers
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('uvicorn').setLevel(logging.INFO)
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)


def get_logger(name):
    """
    Get a logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        logging.Logger instance
    """
    return logging.getLogger(name)


def set_log_level(level):
    """
    Dynamically change the console log level.

    Args:
        level: New logging level (e.g., logging.DEBUG)
    """
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(level)


def get_log_files():
    """
    Get list of current log files.

    Returns:
        dict: Log file paths and their sizes
    """
    log_files = {}

    for root, dirs, files in os.walk(LOG_DIR):
        for file in files:
            if file.endswith('.log'):
                filepath = os.path.join(root, file)
                relative_path = os.path.relpath(filepath, LOG_DIR)
                size = os.path.getsize(filepath)
                log_files[relative_path] = {
                    'path': filepath,
                    'size': size,
                    'size_human': format_size(size)
                }

    return log_files


def format_size(size_bytes):
    """Format byte size to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def clear_logs():
    """
    Clear all log files (for maintenance).

    Warning: This deletes all log content!
    """
    logger = logging.getLogger(__name__)
    logger.warning("Clearing all log files...")

    for root, dirs, files in os.walk(LOG_DIR):
        for file in files:
            if file.endswith('.log'):
                filepath = os.path.join(root, file)
                try:
                    open(filepath, 'w').close()
                    logger.info(f"  Cleared: {filepath}")
                except Exception as e:
                    logger.error(f"  Failed to clear {filepath}: {e}")


# Convenience function for quick setup
def quick_setup(debug=False):
    """
    Quick logging setup for development.

    Args:
        debug: If True, set console to DEBUG level
    """
    console_level = logging.DEBUG if debug else logging.INFO
    setup_logging(console_level=console_level)
