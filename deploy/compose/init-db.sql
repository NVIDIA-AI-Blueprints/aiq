-- =============================================================================
-- AI-Q Blueprint - Database Initialization
-- This script runs on first PostgreSQL startup (fresh volume only)
-- =============================================================================
--
-- What this script handles (requires admin privileges):
--   - Creating databases (aiq_checkpoints)
--   - Granting permissions
--   - Creating NAT JobStore table (job_info)
--   - Creating performance indices
--
-- What the app handles automatically:
--   - job_events table (event_store.py creates via SQLAlchemy)
--   - LangGraph checkpoint tables (AsyncPostgresSaver creates them)
--   - summaries table (summary_store.py creates if not exists)
--
-- =============================================================================

-- Create checkpoints database for LangGraph agent state
CREATE DATABASE aiq_checkpoints;

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE aiq_jobs TO aiq;
GRANT ALL PRIVILEGES ON DATABASE aiq_checkpoints TO aiq;

-- =============================================================================
-- Create job store table in aiq_jobs database
-- Note: job_events table is created by the app (event_store.py)
-- =============================================================================
\connect aiq_jobs

-- Job metadata table (NAT JobStore - not auto-created by NAT)
CREATE TABLE IF NOT EXISTS job_info (
    job_id VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL,
    config_file VARCHAR,
    error VARCHAR,
    output_path VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    expiry_seconds INTEGER,
    output VARCHAR,
    is_expired BOOLEAN DEFAULT FALSE
);

-- Performance indices
CREATE INDEX IF NOT EXISTS idx_job_info_status ON job_info(status);
CREATE INDEX IF NOT EXISTS idx_job_info_created_at ON job_info(created_at);
