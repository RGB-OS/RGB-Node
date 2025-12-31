"""Storage for withdrawal state."""
from datetime import datetime
from typing import Optional
from src.bitcoinl1.model import WithdrawalState, WithdrawalStatus

# In-memory storage for withdrawals
withdrawals: dict[str, WithdrawalState] = {}


def get_withdrawal(withdrawal_id: str) -> Optional[WithdrawalState]:
    """
    Get withdrawal by ID.
    
    Args:
        withdrawal_id: Withdrawal ID
        
    Returns:
        WithdrawalState or None if not found
    """
    return withdrawals.get(withdrawal_id)


def get_withdrawal_by_idempotency_key(idempotency_key: str) -> Optional[WithdrawalState]:
    """
    Get withdrawal by idempotency key.
    
    Args:
        idempotency_key: Idempotency key
        
    Returns:
        WithdrawalState or None if not found
    """
    for withdrawal in withdrawals.values():
        if withdrawal.idempotency_key == idempotency_key:
            return withdrawal
    return None


def save_withdrawal(withdrawal: WithdrawalState) -> None:
    """
    Save or update withdrawal state.
    
    Args:
        withdrawal: Withdrawal state to save
    """
    withdrawals[withdrawal.withdrawal_id] = withdrawal


def update_withdrawal_status(
    withdrawal_id: str,
    status: WithdrawalStatus,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    retryable: bool = False
) -> None:
    """
    Update withdrawal status.
    
    Args:
        withdrawal_id: Withdrawal ID
        status: New status
        error_code: Optional error code
        error_message: Optional error message
        retryable: Whether the error is retryable
    """
    if withdrawal_id in withdrawals:
        withdrawal = withdrawals[withdrawal_id]
        withdrawal.status = status
        withdrawal.updated_at = int(datetime.utcnow().timestamp())
        withdrawal.attempt_count += 1
        withdrawal.last_attempt_at = int(datetime.utcnow().timestamp())
        
        if error_code:
            withdrawal.error_code = error_code
        if error_message:
            withdrawal.error_message = error_message
        withdrawal.retryable = retryable

