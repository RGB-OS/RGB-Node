"""
Utility functions for workers.

Shared utilities for retry logic, logging, and common operations.
"""
import time
import logging
from functools import wraps
from typing import Callable, TypeVar, Any, Optional
from workers.config import MAX_RETRIES, RETRY_DELAY_BASE

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_with_backoff(
    max_attempts: int = MAX_RETRIES,
    base_delay: int = RETRY_DELAY_BASE,
    shutdown_flag: Optional[Callable[[], bool]] = None
) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
        shutdown_flag: Optional callable that returns True if shutdown requested
    
    Example:
        @retry_with_backoff(max_attempts=5, base_delay=2)
        def my_function():
            # function that may fail
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            attempts = 0
            while attempts < max_attempts:
                if shutdown_flag and shutdown_flag():
                    raise InterruptedError("Shutdown requested")
                
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    
                    delay = base_delay * (2 ** (attempts - 1))
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempts}/{max_attempts}), "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
            
            raise Exception(f"{func.__name__} failed after {max_attempts} attempts")
        return wrapper
    return decorator


def format_wallet_id(xpub_van: str, length: int = 5) -> str:
    """
    Format wallet ID for logging (truncated with ellipsis).
    
    Args:
        xpub_van: Full wallet identifier
        length: Number of characters to show at start and end
    
    Returns:
        Formatted string like "abcde...vwxyz"
    """
    if len(xpub_van) <= length * 2:
        return xpub_van
    return f"{xpub_van[:length]}...{xpub_van[-length:]}"


def normalize_transfer_status(status: Any) -> str:
    """
    Normalize transfer status to string.
    
    Handles enum objects, integers, and strings.
    
    Args:
        status: Transfer status (enum, int, or str)
    
    Returns:
        Normalized status string (lowercase)
    """
    if hasattr(status, 'name'):
        return status.name.lower()
    elif isinstance(status, int):
        # TransferStatus: SETTLED=2, FAILED=3
        return 'settled' if status == 2 else 'failed'
    else:
        return str(status).lower()

