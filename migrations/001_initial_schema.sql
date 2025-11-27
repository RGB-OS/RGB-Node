-- PostgreSQL schema for RGB Node refresh queue and watchers

-- Refresh jobs queue
CREATE TABLE IF NOT EXISTS refresh_jobs (
    id SERIAL PRIMARY KEY,
    job_id UUID UNIQUE NOT NULL,
    xpub_van VARCHAR(255) NOT NULL,
    xpub_col VARCHAR(255) NOT NULL,
    master_fingerprint VARCHAR(255) NOT NULL,
    trigger VARCHAR(50) NOT NULL DEFAULT 'manual',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 10,
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    error_message TEXT,
    CONSTRAINT valid_status CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_refresh_jobs_status ON refresh_jobs(status);
CREATE INDEX IF NOT EXISTS idx_refresh_jobs_created_at ON refresh_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_refresh_jobs_xpub_van ON refresh_jobs(xpub_van);

-- Active watchers
CREATE TABLE IF NOT EXISTS refresh_watchers (
    id SERIAL PRIMARY KEY,
    xpub_van VARCHAR(255) NOT NULL,
    xpub_col VARCHAR(255) NOT NULL,
    master_fingerprint VARCHAR(255) NOT NULL,
    recipient_id VARCHAR(255) NOT NULL,
    asset_id VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'watching',
    refresh_count INTEGER DEFAULT 0,
    last_refresh TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    CONSTRAINT unique_watcher UNIQUE(xpub_van, recipient_id),
    CONSTRAINT valid_watcher_status CHECK (status IN ('watching', 'settled', 'failed', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_refresh_watchers_status ON refresh_watchers(status);
CREATE INDEX IF NOT EXISTS idx_refresh_watchers_expires_at ON refresh_watchers(expires_at);
CREATE INDEX IF NOT EXISTS idx_refresh_watchers_xpub ON refresh_watchers(xpub_van);

-- Wallet locks (for preventing concurrent refreshes)
CREATE TABLE IF NOT EXISTS wallet_locks (
    xpub_van VARCHAR(255) PRIMARY KEY,
    locked_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wallet_locks_expires_at ON wallet_locks(expires_at);

-- Function to clean up expired locks
CREATE OR REPLACE FUNCTION cleanup_expired_locks()
RETURNS void AS $$
BEGIN
    DELETE FROM wallet_locks WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

