"""
Worker configuration.

Centralized configuration management for the refresh worker.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# API Configuration
API_URL = os.getenv("API_URL", "http://localhost:8000")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "60"))

# Worker Configuration
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "30"))
MAX_RETRIES = int(os.getenv("MAX_REFRESH_RETRIES", "10"))
RETRY_DELAY_BASE = int(os.getenv("RETRY_DELAY_BASE", "5"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1"))

# Wallet Worker Configuration
WALLET_WORKER_IDLE_TIMEOUT = int(os.getenv("WALLET_WORKER_IDLE_TIMEOUT", "60"))  # Seconds before terminating idle process
WALLET_WORKER_POLL_INTERVAL = int(os.getenv("WALLET_WORKER_POLL_INTERVAL", "5"))  # How often to check for work
MAX_WALLET_PROCESSES = int(os.getenv("MAX_WALLET_PROCESSES", "50"))  # Maximum concurrent wallet worker processes

# Watcher Configuration
INVOICE_WATCHER_EXPIRATION = int(os.getenv("INVOICE_WATCHER_EXPIRATION", "180"))  # 3 minutes for invoice_created without asset_id
WALLET_LOCK_TTL = int(os.getenv("WALLET_LOCK_TTL", "30"))  # Wallet lock TTL in seconds

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Validation
if not API_URL:
    raise ValueError("API_URL environment variable is required")

