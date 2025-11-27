"""
Job processor.

Routes jobs to appropriate handlers and manages job lifecycle.
"""
import logging
from typing import Dict, Any
from workers.processors.unified_handler import process_wallet_unified
from src.queue import mark_job_completed, mark_job_failed

logger = logging.getLogger(__name__)


def validate_job(job: Dict[str, Any]) -> bool:
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


def process_job(job: Dict[str, Any], shutdown_flag: callable) -> None:
    """
    Process a refresh job from the queue.
    
    All jobs are wallet refresh jobs (one per wallet).
    
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
    
    trigger = job.get('trigger', 'manual')
    attempts = job.get('attempts', 0)
    
    logger.info(
        f"[JobProcessor] Processing job {job_id}: trigger={trigger}"
    )
    
    try:
        # All jobs are now wallet refresh jobs (one per wallet)
        process_wallet_unified(job, shutdown_flag)
        mark_job_completed(job_id)
    except Exception as e:
        logger.error(
            f"[JobProcessor] Error processing job {job_id}: {e}", exc_info=True
        )
        mark_job_failed(job_id, str(e), attempts + 1)
        return

