"""
Signal handling for graceful shutdown.
"""
import signal
import logging

logger = logging.getLogger(__name__)

# Global shutdown flag
shutdown = False


def get_shutdown_flag() -> bool:
    """
    Get current shutdown status.
    
    Returns:
        True if shutdown requested, False otherwise
    """
    return shutdown


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    global shutdown
    logger.info("Shutdown signal received, finishing current job...")
    shutdown = True


def register_signal_handlers() -> None:
    """Register signal handlers for graceful shutdown."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

