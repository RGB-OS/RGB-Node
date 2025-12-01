-- Add recipient_id and asset_id to refresh_jobs table for invoice_created jobs

ALTER TABLE refresh_jobs 
ADD COLUMN IF NOT EXISTS recipient_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS asset_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_refresh_jobs_recipient_id ON refresh_jobs(recipient_id);
CREATE INDEX IF NOT EXISTS idx_refresh_jobs_asset_id ON refresh_jobs(asset_id);

