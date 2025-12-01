"""
Refresh job queue operations.

Handles job creation, dequeuing, status updates, and querying.
"""
import os
import time
import uuid
import logging
from typing import Optional, Dict, Any, List
from psycopg2.extras import RealDictCursor
from src.database.connection import get_db_connection

logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = int(os.getenv("MAX_REFRESH_RETRIES", "10"))


def enqueue_refresh_job(
    xpub_van: str,
    xpub_col: str,
    master_fingerprint: str,
    trigger: str = "manual",
    recipient_id: Optional[str] = None,
    asset_id: Optional[str] = None
) -> str:
    """
    Enqueue a refresh job to PostgreSQL queue.
    
    Only manages jobs - does NOT create watchers.
    Each job gets a unique UUID, allowing multiple jobs per wallet.
    For invoice_created jobs, recipient_id and asset_id can be provided.
    
    Args:
        xpub_van: Vanilla xpub for wallet identification
        xpub_col: Colored xpub for wallet identification
        master_fingerprint: Master fingerprint for wallet identification
        trigger: What triggered this refresh ("asset_sent", "sync", "manual", "recovery", "invoice_created", etc.)
        recipient_id: Optional recipient ID (for invoice_created jobs)
        asset_id: Optional asset ID (for invoice_created jobs, can be None)
    
    Returns:
        job_id: Unique job identifier (UUID)
        
    Raises:
        psycopg2.Error: If database operation fails
    """
    # Generate unique UUID for each job
    job_id = str(uuid.uuid4())
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Insert new job (each job has unique ID)
                cur.execute("""
                    INSERT INTO refresh_jobs (
                        job_id, xpub_van, xpub_col, master_fingerprint,
                        trigger, recipient_id, asset_id, status, created_at, max_retries
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    RETURNING job_id
                """, (
                    job_id, xpub_van, xpub_col, master_fingerprint,
                    trigger, recipient_id, asset_id, 'pending', MAX_RETRIES
                ))
                
                result = cur.fetchone()
                if result:
                    job_id = result[0]
                    logger.debug(f"Enqueued refresh job {job_id} for {xpub_van}")
                    return job_id
                else:
                    raise Exception("Failed to insert job - no result returned")
    except Exception as e:
        logger.error(f"Failed to enqueue refresh job: {e}")
        raise


def dequeue_refresh_job() -> Optional[Dict[str, Any]]:
    """
    Dequeue a refresh job from PostgreSQL (for worker).
    
    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
    Automatically marks job as 'processing' when dequeued.
    
    Returns:
        Job dictionary or None if no jobs available
        
    Note:
        This function is thread-safe and can be called by multiple workers.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get and lock a pending job
                cur.execute("""
                    SELECT * FROM refresh_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                """)
                
                row = cur.fetchone()
                if not row:
                    return None
                
                # Update status to processing
                cur.execute("""
                    UPDATE refresh_jobs
                    SET status = 'processing', processed_at = NOW()
                    WHERE id = %s
                """, (row['id'],))
                
                # Convert to dict and normalize timestamps
                job = dict(row)
                _normalize_timestamps(job)
                
                return job
    except Exception as e:
        logger.error(f"Failed to dequeue refresh job: {e}")
        return None


def mark_job_completed(job_id: str) -> None:
    """
    Mark a job as completed.
    
    Args:
        job_id: Job identifier
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE refresh_jobs
                    SET status = 'completed'
                    WHERE job_id = %s
                """, (job_id,))
    except Exception as e:
        logger.error(f"Failed to mark job completed: {e}")


def mark_job_failed(job_id: str, error_message: str, attempts: int) -> None:
    """
    Mark a job as failed or retry.
    
    Args:
        job_id: Job identifier
        error_message: Error message describing the failure
        attempts: Number of attempts made (used to determine if job should be retried)
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                status = 'failed' if attempts >= MAX_RETRIES else 'pending'
                cur.execute("""
                    UPDATE refresh_jobs
                    SET status = %s, attempts = %s, error_message = %s
                    WHERE job_id = %s
                """, (status, attempts, error_message, job_id))
    except Exception as e:
        logger.error(f"Failed to mark job failed: {e}")


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get status of a refresh job.
    
    Args:
        job_id: Job identifier
    
    Returns:
        Job status dictionary or None if not found
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM refresh_jobs
                    WHERE job_id = %s
                """, (job_id,))
                
                row = cur.fetchone()
                if not row:
                    return None
                
                job = dict(row)
                _normalize_timestamps(job)
                
                return job
    except Exception as e:
        logger.error(f"Failed to get job status: {e}")
        return None


def get_pending_jobs_for_wallet(xpub_van: str) -> List[Dict[str, Any]]:
    """
    Get all pending jobs for a specific wallet.
    
    Args:
        xpub_van: Wallet identifier
        
    Returns:
        List of pending job dictionaries
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM refresh_jobs
                    WHERE xpub_van = %s AND status = 'pending'
                    ORDER BY created_at ASC
                """, (xpub_van,))
                
                jobs = []
                for row in cur.fetchall():
                    job = dict(row)
                    _normalize_timestamps(job)
                    jobs.append(job)
                
                return jobs
    except Exception as e:
        logger.error(f"Failed to get pending jobs for wallet: {e}")
        return []


def dequeue_job_for_wallet(xpub_van: str) -> Optional[Dict[str, Any]]:
    """
    Dequeue one pending job for a specific wallet.
    
    Uses SELECT FOR UPDATE SKIP LOCKED for safe concurrent access.
    Automatically marks job as 'processing' when dequeued.
    
    Args:
        xpub_van: Wallet identifier
        
    Returns:
        Job dictionary or None if no jobs available
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get and lock a pending job for this wallet
                cur.execute("""
                    SELECT * FROM refresh_jobs
                    WHERE xpub_van = %s AND status = 'pending'
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                """, (xpub_van,))
                
                row = cur.fetchone()
                if not row:
                    return None
                
                # Update status to processing
                cur.execute("""
                    UPDATE refresh_jobs
                    SET status = 'processing', processed_at = NOW()
                    WHERE id = %s
                """, (row['id'],))
                
                # Convert to dict and normalize timestamps
                job = dict(row)
                _normalize_timestamps(job)
                
                return job
    except Exception as e:
        logger.error(f"Failed to dequeue job for wallet: {e}")
        return None


def _normalize_timestamps(data: Dict[str, Any]) -> None:
    """
    Normalize PostgreSQL timestamps to Unix timestamps (integers).
    
    Args:
        data: Dictionary containing timestamp fields to normalize (modified in-place)
    """
    timestamp_fields = ['created_at', 'processed_at']
    for field in timestamp_fields:
        if field in data and data[field] is not None:
            data[field] = int(data[field].timestamp())

