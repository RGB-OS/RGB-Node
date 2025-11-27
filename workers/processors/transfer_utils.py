"""
Transfer utility functions.

Shared functions for checking transfer status across different processors.
"""
import time
from typing import Dict, Any


def is_transfer_completed(transfer: Dict[str, Any]) -> bool:
    """Check if transfer is in terminal state."""
    status = transfer.get('status')
    
    # Handle enum object (if not serialized)
    if hasattr(status, 'name'):
        status = status.name
    # Handle enum value (integer)
    elif isinstance(status, int):
        # TransferStatus: SETTLED=2, FAILED=3
        return status in [2, 3]
    
    # Handle string (most common from JSON serialization)
    if isinstance(status, str):
        return status.upper() in ['SETTLED', 'FAILED']
    
    return False


def is_transfer_expired(transfer: Dict[str, Any]) -> bool:
    """Check if transfer has expired."""
    expiration = transfer.get('expiration')
    if not expiration:
        return False
    
    now = int(time.time())
    kind = transfer.get('kind')
    
    # Handle enum object (if not serialized)
    if hasattr(kind, 'name'):
        kind = kind.name
    # Handle enum value (integer)
    elif isinstance(kind, int):
        # TransferKind: RECEIVE_BLIND = 1
        if kind != 1:
            return False
        kind = 'RECEIVE_BLIND'
    
    # Only RECEIVE_BLIND transfers can expire
    if isinstance(kind, str) and kind.upper() == 'RECEIVE_BLIND' and expiration < now:
        return True
    
    return False

