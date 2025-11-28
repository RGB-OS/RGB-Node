"""
Job processor.

Routes jobs to appropriate handlers and manages job lifecycle.
"""
import logging
from workers.processors.unified_handler import process_wallet_unified
from workers.models import Job, WalletCredentials
from workers.utils import format_wallet_id
from workers.config import INVOICE_WATCHER_EXPIRATION
from src.queue import (
    mark_job_completed,
    mark_job_failed,
    create_watcher,
    get_watcher_status,
)

logger = logging.getLogger(__name__)


def validate_job(job: dict) -> bool:
    """
    Validate job structure has required fields.
    
    Args:
        job: Job dictionary to validate
    
    Returns:
        True if valid, False otherwise
    """
    required_fields = ['xpub_van', 'xpub_col', 'master_fingerprint']
    for field in required_fields:
        if field not in job:
            logger.error(f"Job missing required field: {field}")
            return False
    return True


def _handle_invoice_created_without_asset(job_obj: Job) -> None:
    """
    Handle invoice_created job without asset_id.
    Creates watcher with 3 min expiration.
    
    Args:
        job_obj: Job object
    """
    credentials = job_obj.get_credentials()
    wallet_id = format_wallet_id(credentials.xpub_van)
    
    existing_watcher = get_watcher_status(credentials.xpub_van, job_obj.recipient_id)
    if existing_watcher:
        logger.info(
            f"[JobProcessor] Watcher already exists for {wallet_id}:{job_obj.recipient_id}, "
            f"skipping creation"
        )
        return
    
    create_watcher(
        xpub_van=credentials.xpub_van,
        xpub_col=credentials.xpub_col,
        master_fingerprint=credentials.master_fingerprint,
        recipient_id=job_obj.recipient_id,
        asset_id=None,
        expiration_seconds=INVOICE_WATCHER_EXPIRATION
    )
    logger.info(
        f"[JobProcessor] Created watcher for invoice {job_obj.recipient_id} "
        f"({INVOICE_WATCHER_EXPIRATION}s expiration)"
    )


def process_job(job: dict, shutdown_flag: callable) -> None:
    """
    Process a refresh job from the queue.
    
    Args:
        job: Job dictionary from PostgreSQL queue
        shutdown_flag: Callable that returns True if shutdown requested
    """
    if not validate_job(job):
        logger.error(f"Invalid job structure: {job}")
        job_id = job.get('job_id', '')
        if job_id:
            mark_job_failed(job_id, "Invalid job structure", job.get('attempts', 0) + 1)
        return
    
    job_id = job.get('job_id')
    if not job_id:
        logger.error(f"Job missing job_id: {job}")
        return
    
    try:
        job_obj = Job.from_dict(job)
        
        logger.info(
            f"[JobProcessor] Processing job {job_id}: trigger={job_obj.trigger}, "
            f"recipient_id={job_obj.recipient_id}, asset_id={job_obj.asset_id}"
        )
        
        if job_obj.trigger == "invoice_created" and job_obj.recipient_id and not job_obj.asset_id:
            _handle_invoice_created_without_asset(job_obj)
            mark_job_completed(job_id)
        else:
            process_wallet_unified(job, shutdown_flag)
            mark_job_completed(job_id)
    except Exception as e:
        logger.error(
            f"[JobProcessor] Error processing job {job_id}: {e}", exc_info=True
        )
        mark_job_failed(job_id, str(e), job.get('attempts', 0) + 1)
