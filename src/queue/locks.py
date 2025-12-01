"""
Distributed locking operations.

Provides wallet-level locking to prevent concurrent refresh operations.
"""
import time
import logging
from src.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def acquire_wallet_lock(xpub_van: str, ttl: int = 30) -> bool:
    """
    Acquire a lock for a wallet to prevent concurrent refreshes.
    
    Uses PostgreSQL's ON CONFLICT to implement distributed locking.
    Automatically cleans up expired locks before attempting to acquire.
    
    Args:
        xpub_van: Vanilla xpub (wallet identifier)
        ttl: Lock time-to-live in seconds (default: 30)
    
    Returns:
        True if lock acquired, False if already locked
        
    Example:
        if acquire_wallet_lock("xpub123"):
            try:
                # Perform refresh operation
                refresh_wallet()
            finally:
                release_wallet_lock("xpub123")
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Clean up expired locks first
                cur.execute("SELECT cleanup_expired_locks()")
                
                # Try to insert lock
                expires_at = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(time.time() + ttl))
                cur.execute("""
                    INSERT INTO wallet_locks (xpub_van, expires_at)
                    VALUES (%s, %s)
                    ON CONFLICT (xpub_van) DO NOTHING
                    RETURNING xpub_van
                """, (xpub_van, expires_at))
                
                return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Failed to acquire wallet lock: {e}")
        return False


def release_wallet_lock(xpub_van: str) -> None:
    """
    Release wallet lock.
    
    Args:
        xpub_van: Vanilla xpub (wallet identifier)
        
    Note:
        Safe to call even if lock doesn't exist (no-op).
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM wallet_locks
                    WHERE xpub_van = %s
                """, (xpub_van,))
    except Exception as e:
        logger.error(f"Failed to release wallet lock: {e}")

