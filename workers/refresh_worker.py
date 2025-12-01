"""
Refresh Worker Service (Main Orchestrator)

Main entry point that monitors the job queue and spawns wallet-specific worker processes.
One process per wallet ensures sequential processing within each wallet.
"""
import os
import sys
import time
import subprocess
import logging
from typing import Dict, Optional
from subprocess import Popen
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import worker modules
from workers.config import API_URL, POLL_INTERVAL, LOG_LEVEL, MAX_WALLET_PROCESSES
from workers.signals import register_signal_handlers, get_shutdown_flag
from workers.api.client import get_api_client
from workers.utils import format_wallet_id
from src.database.connection import get_db_connection
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Track active wallet processes: {xpub_van: subprocess.Popen}
active_processes: Dict[str, Popen] = {}


def get_wallet_worker_script_path() -> str:
    """Get path to wallet_worker.py script."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'wallet_worker.py')


def spawn_wallet_worker(xpub_van: str) -> Optional[Popen]:
    """
    Spawn a wallet-specific worker process.
    
    Args:
        xpub_van: Wallet identifier
        
    Returns:
        subprocess.Process or None if spawn failed
    """
    script_path = get_wallet_worker_script_path()
    python_executable = sys.executable
    
    try:
        process = subprocess.Popen(
            [python_executable, script_path, '--wallet', xpub_van],
            text=True
        )
        
        wallet_id = format_wallet_id(xpub_van)
        logger.info(
            f"[RefreshWorker] Spawned wallet worker for {wallet_id} (PID: {process.pid})"
        )
        
        return process
    except Exception as e:
        wallet_id = format_wallet_id(xpub_van)
        logger.error(
            f"[RefreshWorker] Failed to spawn wallet worker for {wallet_id}: {e}"
        )
        return None


def cleanup_dead_processes() -> None:
    """Remove dead processes from active_processes dictionary."""
    global active_processes
    
    dead_wallets = []
    for xpub_van, process in active_processes.items():
        if process.poll() is not None:
            dead_wallets.append(xpub_van)
            wallet_id = format_wallet_id(xpub_van)
            logger.debug(
                f"[RefreshWorker] Wallet worker for {wallet_id} "
                f"terminated (exit code: {process.returncode})"
            )
    
    for xpub_van in dead_wallets:
        active_processes.pop(xpub_van, None)


def terminate_all_processes() -> None:
    """Terminate all active wallet worker processes."""
    global active_processes
    
    if not active_processes:
        return
    
    logger.info(f"Terminating {len(active_processes)} active wallet worker process(es)...")
    
    # Send SIGTERM to all processes
    for xpub_van, process in active_processes.items():
        try:
            if process.poll() is None:  # Process still running
                wallet_id = format_wallet_id(xpub_van)
                logger.info(
                    f"[RefreshWorker] Terminating wallet worker for {wallet_id}"
                )
                process.terminate()
        except Exception as e:
            wallet_id = format_wallet_id(xpub_van)
            logger.error(f"Error terminating process for {wallet_id}: {e}")
    
    # Wait for processes to terminate (with timeout)
    timeout = 10
    start_time = time.time()
    
    while active_processes and (time.time() - start_time) < timeout:
        cleanup_dead_processes()
        if active_processes:
            time.sleep(0.5)
    
    # Force kill any remaining processes
    for xpub_van, process in list(active_processes.items()):
        try:
            if process.poll() is None:
                wallet_id = format_wallet_id(xpub_van)
                logger.warning(
                    f"[RefreshWorker] Force killing wallet worker for {wallet_id}"
                )
                process.kill()
        except Exception as e:
            wallet_id = format_wallet_id(xpub_van)
            logger.error(f"Error killing process for {wallet_id}: {e}")
    
    active_processes.clear()
    logger.info("All wallet worker processes terminated")


def main() -> None:
    """
    Main orchestrator loop - polls PostgreSQL queue for jobs and spawns wallet worker processes.
    
    One process per wallet ensures sequential processing within each wallet.
    Different wallets run in parallel (separate processes).
    """
    logger.info("Starting refresh worker (main orchestrator)...")
    logger.info(f"API URL: {API_URL}")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    
    # Register signal handlers
    register_signal_handlers()
    
    # Health check
    api_client = get_api_client()
    if api_client.health_check():
        logger.info("API connection successful")
    else:
        logger.warning("API health check failed (may be normal)")
    
    # Recover active watchers on startup (create pending jobs for wallets with active watchers)
    try:
        from src.queue.recovery import recover_active_watchers
        logger.info("Recovering active watchers on startup...")
        recovered = recover_active_watchers()
        logger.info(f"Recovery complete: {recovered} watchers recovered")
    except Exception as e:
        logger.error(f"Failed to recover active watchers on startup: {e}", exc_info=True)
    
    last_heartbeat = time.time()
    heartbeat_interval = 30
    last_cleanup = time.time()
    cleanup_interval = 10  # Clean up dead processes every 10 seconds
    
    try:
        while not get_shutdown_flag():
            try:
                current_time = time.time()
                if current_time - last_cleanup >= cleanup_interval:
                    cleanup_dead_processes()
                    last_cleanup = current_time
                
                try:
                    with get_db_connection() as conn:
                        with conn.cursor(cursor_factory=RealDictCursor) as cur:
                            cur.execute("""
                                SELECT DISTINCT xpub_van
                                FROM refresh_jobs
                                WHERE status = 'pending'
                            """)
                            
                            wallets_with_pending_jobs = [row['xpub_van'] for row in cur.fetchall()]
                            
                            cur.execute("""
                                SELECT DISTINCT xpub_van
                                FROM refresh_watchers
                                WHERE status = 'watching'
                                AND (expires_at IS NULL OR expires_at > NOW())
                            """)
                            
                            wallets_with_active_watchers = [row['xpub_van'] for row in cur.fetchall()]
                            
                            # Combine both sets (wallets that need processing)
                            wallets_needing_processing = set(wallets_with_pending_jobs) | set(wallets_with_active_watchers)
                            
                            for xpub_van in wallets_needing_processing:
                                if xpub_van in active_processes:
                                    process = active_processes[xpub_van]
                                    if process.poll() is None:
                                        continue
                                    else:
                                        wallet_id = format_wallet_id(xpub_van)
                                        logger.warning(
                                            f"[RefreshWorker] Wallet worker for {wallet_id} died, will respawn"
                                        )
                                        active_processes.pop(xpub_van, None)
                                
                                running_count = len([p for p in active_processes.values() if p.poll() is None])
                                
                                if running_count >= MAX_WALLET_PROCESSES:
                                    wallet_id = format_wallet_id(xpub_van)
                                    logger.warning(
                                        f"[RefreshWorker] Maximum process limit reached ({MAX_WALLET_PROCESSES}), "
                                        f"skipping wallet {wallet_id}"
                                    )
                                    continue
                                
                                process = spawn_wallet_worker(xpub_van)
                                if process:
                                    active_processes[xpub_van] = process
                                    running_count = len([p for p in active_processes.values() if p.poll() is None])
                                    wallet_id = format_wallet_id(xpub_van)
                                    logger.info(
                                        f"[RefreshWorker] Wallet worker spawned for wallet {wallet_id} "
                                        f"(active processes: {running_count}/{MAX_WALLET_PROCESSES})"
                                    )
                except Exception as e:
                    logger.error(f"Error checking for wallets with pending jobs: {e}")
                else:
                    if current_time - last_heartbeat >= heartbeat_interval:
                        logger.debug(
                            f"[RefreshWorker] Waiting for jobs... "
                            f"(active wallet processes: {len(active_processes)})"
                        )
                        last_heartbeat = current_time
                
                time.sleep(POLL_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                time.sleep(POLL_INTERVAL)
    
    finally:
        # Terminate all wallet worker processes
        terminate_all_processes()
        
        # Close API client
        try:
            api_client.close()
        except Exception as e:
            logger.error(f"Error closing API client: {e}")
        
        logger.info("Refresh worker (orchestrator) stopped")


if __name__ == "__main__":
    main()
