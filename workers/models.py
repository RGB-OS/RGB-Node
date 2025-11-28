"""
Data models for workers.

Type-safe data classes for jobs, watchers, transfers, and wallet credentials.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class WalletCredentials:
    """Wallet credentials for API calls."""
    xpub_van: str
    xpub_col: str
    master_fingerprint: str
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for API calls."""
        return {
            'xpub_van': self.xpub_van,
            'xpub_col': self.xpub_col,
            'master_fingerprint': self.master_fingerprint,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WalletCredentials':
        """Create from dictionary."""
        return cls(
            xpub_van=data['xpub_van'],
            xpub_col=data['xpub_col'],
            master_fingerprint=data['master_fingerprint'],
        )


@dataclass
class Job:
    """Refresh job model."""
    job_id: str
    xpub_van: str
    xpub_col: str
    master_fingerprint: str
    trigger: str
    recipient_id: Optional[str] = None
    asset_id: Optional[str] = None
    status: str = 'pending'
    attempts: int = 0
    max_retries: int = 10
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'job_id': self.job_id,
            'xpub_van': self.xpub_van,
            'xpub_col': self.xpub_col,
            'master_fingerprint': self.master_fingerprint,
            'trigger': self.trigger,
            'recipient_id': self.recipient_id,
            'asset_id': self.asset_id,
            'status': self.status,
            'attempts': self.attempts,
            'max_retries': self.max_retries,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Job':
        """Create from dictionary."""
        return cls(
            job_id=data.get('job_id', ''),
            xpub_van=data['xpub_van'],
            xpub_col=data['xpub_col'],
            master_fingerprint=data['master_fingerprint'],
            trigger=data.get('trigger', 'manual'),
            recipient_id=data.get('recipient_id'),
            asset_id=data.get('asset_id'),
            status=data.get('status', 'pending'),
            attempts=data.get('attempts', 0),
            max_retries=data.get('max_retries', 10),
        )
    
    def get_credentials(self) -> WalletCredentials:
        """Get wallet credentials from job."""
        return WalletCredentials(
            xpub_van=self.xpub_van,
            xpub_col=self.xpub_col,
            master_fingerprint=self.master_fingerprint,
        )


@dataclass
class Watcher:
    """Watcher model."""
    xpub_van: str
    xpub_col: str
    master_fingerprint: str
    recipient_id: str
    asset_id: Optional[str] = None
    status: str = 'watching'
    refresh_count: int = 0
    expires_at: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'xpub_van': self.xpub_van,
            'xpub_col': self.xpub_col,
            'master_fingerprint': self.master_fingerprint,
            'recipient_id': self.recipient_id,
            'asset_id': self.asset_id,
            'status': self.status,
            'refresh_count': self.refresh_count,
            'expires_at': self.expires_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Watcher':
        """Create from dictionary."""
        return cls(
            xpub_van=data['xpub_van'],
            xpub_col=data['xpub_col'],
            master_fingerprint=data['master_fingerprint'],
            recipient_id=data['recipient_id'],
            asset_id=data.get('asset_id'),
            status=data.get('status', 'watching'),
            refresh_count=data.get('refresh_count', 0),
            expires_at=data.get('expires_at'),
        )
    
    def get_credentials(self) -> WalletCredentials:
        """Get wallet credentials from watcher."""
        return WalletCredentials(
            xpub_van=self.xpub_van,
            xpub_col=self.xpub_col,
            master_fingerprint=self.master_fingerprint,
        )


@dataclass
class Transfer:
    """Transfer model."""
    recipient_id: Optional[str] = None
    asset_id: Optional[str] = None
    status: Any = None
    kind: Any = None
    expiration: Optional[int] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transfer':
        """Create from dictionary."""
        return cls(
            recipient_id=data.get('recipient_id'),
            asset_id=data.get('asset_id'),
            status=data.get('status'),
            kind=data.get('kind'),
            expiration=data.get('expiration'),
        )

