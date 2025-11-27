"""
Watcher management operations.

Handles watcher creation, status updates, and querying.
"""
import os
import time
import logging
from typing import Optional, Dict, Any, List
from psycopg2.extras import RealDictCursor
from src.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def create_watcher(
    xpub_van: str,
    xpub_col: str,
    master_fingerprint: str,
    recipient_id: str,
    asset_id: Optional[str] = None
) -> None:
    """
    Create or update a watcher entry in the database.
    
    Args:
        xpub_van: Vanilla xpub
        xpub_col: Colored xpub
        master_fingerprint: Master fingerprint
        recipient_id: Recipient ID (unique identifier for the transfer - REQUIRED)
        asset_id: Asset ID (optional)
    """
    try:
        expires_at = int(time.time()) + int(os.getenv("WATCHER_TTL", "86400"))
        expires_at_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(expires_at))
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO refresh_watchers (
                        xpub_van, xpub_col, master_fingerprint, recipient_id, 
                        asset_id,
                        status, created_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (xpub_van, recipient_id) 
                    DO UPDATE SET
                        status = 'watching',
                        expires_at = %s,
                        refresh_count = 0,
                        xpub_col = EXCLUDED.xpub_col,
                        master_fingerprint = EXCLUDED.master_fingerprint,
                        asset_id = EXCLUDED.asset_id
                """, (
                    xpub_van, xpub_col, master_fingerprint, recipient_id, 
                    asset_id,
                    'watching', expires_at_str, expires_at_str
                ))
                logger.debug(f"Created/updated watcher for {xpub_van}:{recipient_id}")
    except Exception as e:
        logger.error(f"Failed to create watcher: {e}")
        raise


def get_watcher_status(xpub_van: str, recipient_id: str) -> Optional[Dict[str, Any]]:
    """
    Get status of a watcher for a specific recipient.
    
    Args:
        xpub_van: Vanilla xpub
        recipient_id: Recipient ID
    
    Returns:
        Watcher status dictionary or None if not found
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM refresh_watchers
                    WHERE xpub_van = %s AND recipient_id = %s
                """, (xpub_van, recipient_id))
                
                row = cur.fetchone()
                if not row:
                    return None
                
                watcher = dict(row)
                _normalize_watcher_timestamps(watcher)
                
                return watcher
    except Exception as e:
        logger.error(f"Failed to get watcher status: {e}")
        return None


def update_watcher_status(
    xpub_van: str,
    recipient_id: str,
    status: str,
    refresh_count: Optional[int] = None
) -> None:
    """
    Update watcher status in PostgreSQL.
    
    Args:
        xpub_van: Vanilla xpub
        recipient_id: Recipient ID
        status: New status ("watching", "settled", "failed")
        refresh_count: Optional refresh count update
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if refresh_count is not None:
                    cur.execute("""
                        UPDATE refresh_watchers
                        SET status = %s, last_refresh = NOW(), refresh_count = %s
                        WHERE xpub_van = %s AND recipient_id = %s
                    """, (status, refresh_count, xpub_van, recipient_id))
                else:
                    cur.execute("""
                        UPDATE refresh_watchers
                        SET status = %s, last_refresh = NOW()
                        WHERE xpub_van = %s AND recipient_id = %s
                    """, (status, xpub_van, recipient_id))
                
    except Exception as e:
        logger.error(f"Failed to update watcher status: {e}")


def stop_watcher(xpub_van: str, recipient_id: str) -> None:
    """
    Stop a watcher by deleting it from PostgreSQL.
    
    Args:
        xpub_van: Vanilla xpub
        recipient_id: Recipient ID
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM refresh_watchers
                    WHERE xpub_van = %s AND recipient_id = %s
                """, (xpub_van, recipient_id))
    except Exception as e:
        logger.error(f"Failed to stop watcher: {e}")


def get_active_watchers() -> List[Dict[str, Any]]:
    """
    Get all active watchers (for recovery).
    
    Returns:
        List of active watcher dictionaries
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM refresh_watchers
                    WHERE status = 'watching'
                    AND (expires_at IS NULL OR expires_at > NOW())
                """)
                
                watchers = []
                for row in cur.fetchall():
                    watcher = dict(row)
                    _normalize_watcher_timestamps(watcher)
                    watchers.append(watcher)
                
                return watchers
    except Exception as e:
        logger.error(f"Failed to get active watchers: {e}")
        return []


def get_active_watchers_for_wallet(xpub_van: str) -> List[Dict[str, Any]]:
    """
    Get all active watchers for a specific wallet.
    
    Args:
        xpub_van: Wallet identifier
        
    Returns:
        List of active watcher dictionaries for the wallet
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM refresh_watchers
                    WHERE xpub_van = %s
                    AND status = 'watching'
                    AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at ASC
                """, (xpub_van,))
                
                watchers = []
                for row in cur.fetchall():
                    watcher = dict(row)
                    _normalize_watcher_timestamps(watcher)
                    watchers.append(watcher)
                
                return watchers
    except Exception as e:
        logger.error(f"Failed to get active watchers for wallet: {e}")
        return []


def _normalize_watcher_timestamps(watcher: Dict[str, Any]) -> None:
    """
    Normalize watcher timestamp fields to Unix timestamps.
    
    Args:
        watcher: Watcher dictionary (modified in-place)
    """
    timestamp_fields = ['created_at', 'last_refresh', 'expires_at']
    for field in timestamp_fields:
        if field in watcher and watcher[field] is not None:
            watcher[field] = int(watcher[field].timestamp())

