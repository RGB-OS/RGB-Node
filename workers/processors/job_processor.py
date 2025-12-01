"""
Job processor.

Routes jobs to appropriate handlers and manages job lifecycle.
"""
import logging
from workers.processors.unified_handler import process_wallet_unified
from workers.models import Job
from src.queue import (
    mark_job_completed,
    mark_job_failed,
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
        
        process_wallet_unified(job, shutdown_flag)
        mark_job_completed(job_id)
    except Exception as e:
        logger.error(
            f"[JobProcessor] Error processing job {job_id}: {e}", exc_info=True
        )
        mark_job_failed(job_id, str(e), job.get('attempts', 0) + 1)
