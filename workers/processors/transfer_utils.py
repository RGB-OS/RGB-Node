"""
Transfer utility functions.

Shared functions for checking transfer status across different processors.
"""
import time
from typing import Dict, Any, Optional
from src.constant import RGB_INVOICE_DURATION_SECONDS


def get_transfer_identifier(transfer: Optional[Dict[str, Any]] = None, job: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Get transfer identifier from transfer or job.
    
    Uses recipient_id (required for watchers).
    Prioritizes transfer.recipient_id, falls back to job.recipient_id.
    
    Args:
        transfer: Transfer dictionary (may be None)
        job: Job dictionary (may be None)
    
    Returns:
        recipient_id if available, None otherwise
    """
    if transfer:
        recipient_id = transfer.get('recipient_id')
        if recipient_id:
            return recipient_id
    
    if job:
        recipient_id = job.get('recipient_id')
        if recipient_id:
            return recipient_id
    
    return None


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


def can_cancel_transfer(transfer: Dict[str, Any]) -> bool:
    """
    Check if a transfer can be cancelled (failed).
    
    Transfers can only be cancelled if:
    1. Status is WAITING_COUNTERPARTY
    2. Transfer has expiration and it's in the past
    3. Either:
       - Transfer kind is RECEIVE_BLIND, OR
       - expiration + DURATION_RCV_TRANSFER < now
    
    Args:
        transfer: Transfer dictionary
        
    Returns:
        True if transfer can be cancelled, False otherwise
    """
    # Check status is WAITING_COUNTERPARTY
    status = transfer.get('status')
    
    # Normalize status to string
    # TransferStatus enum values: WAITING_COUNTERPARTY=0, WAITING_CONFIRMATIONS=1, SETTLED=2, FAILED=3
    if hasattr(status, 'name'):
        status_normalized = status.name.upper()
    elif isinstance(status, int):
        # Map integer enum values to names
        # TransferStatus: WAITING_COUNTERPARTY = 0
        if status == 0:
            status_normalized = 'WAITING_COUNTERPARTY'
        else:
            status_normalized = str(status).upper()
    elif isinstance(status, str):
        status_normalized = status.upper()
    else:
        # Try to convert to string and check
        status_normalized = str(status).upper()
    
    # Exact match required
    if status_normalized != 'WAITING_COUNTERPARTY':
        return False
    
    # Check expiration exists and is in the past
    expiration = transfer.get('expiration')
    if not expiration:
        return False
    
    now = int(time.time())
    if expiration >= now:
        return False
    
    # Check kind
    kind = transfer.get('kind')
    
    # Normalize kind to string
    if hasattr(kind, 'name'):
        kind_name = kind.name.upper()
    elif isinstance(kind, int):
        # TransferKind: RECEIVE_BLIND = 1
        kind_name = 'RECEIVE_BLIND' if kind == 1 else None
    elif isinstance(kind, str):
        kind_name = kind.upper()
    else:
        kind_name = str(kind).upper() if kind else None
    
    # Check condition: RECEIVE_BLIND OR expiration + DURATION_RCV_TRANSFER < now
    is_receive_blind = kind_name == 'RECEIVE_BLIND'
    expiration_plus_duration = expiration + RGB_INVOICE_DURATION_SECONDS
    
    return is_receive_blind or expiration_plus_duration < now

