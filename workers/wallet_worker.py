"""
Wallet-specific worker process.

Handles all jobs and watchers for a specific wallet sequentially.
One process per wallet ensures no parallel processing for the same wallet.
"""
import os
import sys
import time
import argparse
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import worker modules
from workers.config import (
    WALLET_WORKER_IDLE_TIMEOUT,
    WALLET_WORKER_POLL_INTERVAL,
    LOG_LEVEL
)
from workers.signals import register_signal_handlers, get_shutdown_flag
from workers.processors import process_job
from workers.processors.transfer_watcher import watch_transfer
from src.queue import (
    dequeue_job_for_wallet,
    get_active_watchers_for_wallet,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def process_watchers_for_wallet(xpub_van: str) -> int:
    """
    Process all active watchers for a wallet sequentially.
    
    Args:
        xpub_van: Wallet identifier
        
    Returns:
        Number of watchers processed
    """
    watchers = get_active_watchers_for_wallet(xpub_van)
    if not watchers:
        return 0
    
    logger.info(
        f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
        f"Found {len(watchers)} active watcher(s)"
    )
    
    processed = 0
    for watcher in watchers:
        if get_shutdown_flag():
            break
        
        recipient_id = watcher.get('recipient_id')
        if not recipient_id:
            logger.warning(f"Watcher missing recipient_id: {watcher}")
            continue
        
        # Create job dict for watcher
        watcher_job = {
            'xpub_van': watcher['xpub_van'],
            'xpub_col': watcher['xpub_col'],
            'master_fingerprint': watcher['master_fingerprint'],
            'recipient_id': recipient_id,
            'asset_id': watcher.get('asset_id'),
        }
        
        try:
            logger.info(
                f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                f"Processing watcher for transfer {recipient_id}"
            )
            
            # Process watcher (runs until transfer completes or expires)
            watch_transfer(
                job=watcher_job,
                recipient_id=recipient_id,
                asset_id=watcher.get('asset_id'),
                shutdown_flag=get_shutdown_flag
            )
            
            processed += 1
        except Exception as e:
            logger.error(
                f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                f"Error processing watcher {recipient_id}: {e}", exc_info=True
            )
    
    return processed


def main() -> None:
    """
    Main wallet worker loop.
    
    Processes jobs and watchers for a specific wallet sequentially.
    Terminates after idle timeout if no work is available.
    """
    parser = argparse.ArgumentParser(description='Wallet-specific worker process')
    parser.add_argument('--wallet', required=True, help='Wallet xpub_van identifier')
    args = parser.parse_args()
    
    xpub_van = args.wallet
    
    logger.info(f"Starting wallet worker for {xpub_van[:5]}...{xpub_van[-5:]}")
    logger.info(f"Idle timeout: {WALLET_WORKER_IDLE_TIMEOUT}s")
    logger.info(f"Poll interval: {WALLET_WORKER_POLL_INTERVAL}s")
    
    # Register signal handlers
    register_signal_handlers()
    
    last_work_time = time.time()
    
    try:
        while not get_shutdown_flag():
            has_work = False
            
            # Process pending jobs for this wallet (sequentially)
            while True:
                if get_shutdown_flag():
                    break
                
                job = dequeue_job_for_wallet(xpub_van)
                if not job:
                    break
                
                has_work = True
                last_work_time = time.time()
                
                job_id = job.get('job_id', 'unknown')
                logger.info(
                    f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                    f"Processing job {job_id}"
                )
                
                try:
                    # process_job handles marking job as completed/failed internally
                    process_job(job, get_shutdown_flag)
                    logger.info(
                        f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Job {job_id} completed"
                    )
                except Exception as e:
                    # process_job handles marking job as failed internally, but log error here
                    logger.error(
                        f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"Error processing job {job_id}: {e}", exc_info=True
                    )
            
            # Process watchers for this wallet (sequentially)
            if not get_shutdown_flag():
                processed = process_watchers_for_wallet(xpub_van)
                if processed > 0:
                    has_work = True
                    last_work_time = time.time()
            
            # Check idle timeout
            if not has_work:
                idle_time = time.time() - last_work_time
                if idle_time >= WALLET_WORKER_IDLE_TIMEOUT:
                    logger.info(
                        f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
                        f"No work for {idle_time:.0f}s, terminating"
                    )
                    break
            
            # Sleep before next iteration
            if not get_shutdown_flag():
                time.sleep(WALLET_WORKER_POLL_INTERVAL)
    
    except KeyboardInterrupt:
        logger.info(f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Keyboard interrupt received")
    except Exception as e:
        logger.error(
            f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - "
            f"Unexpected error: {e}", exc_info=True
        )
    finally:
        logger.info(f"[WalletWorker] Wallet {xpub_van[:5]}...{xpub_van[-5:]} - Worker stopped")


if __name__ == "__main__":
    main()

