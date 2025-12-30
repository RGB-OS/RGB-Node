"""Temporary storage for deposit addresses and invoices."""
from typing import Optional
from src.bitcoinl1.model import UnusedDepositAddress

# Storage for deposit address and invoice
deposit_address: Optional[UnusedDepositAddress] = None
cached_asset_invoice: Optional[str] = None
cached_expires_at: Optional[str] = None
cached_batch_transfer_idx: Optional[int] = None
cached_invoice_created_at: Optional[int] = None

