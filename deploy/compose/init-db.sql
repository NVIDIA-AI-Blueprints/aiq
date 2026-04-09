-- =============================================================================
-- AI-Q Blueprint - Database Initialization (idempotent — safe to re-run)
-- =============================================================================
--
-- What this script handles:
--   - Creating databases (aiq_checkpoints)
--   - Granting permissions
--   - Creating NAT JobStore table (job_info)
--   - Creating performance indices
--
-- What the app handles automatically:
--   - job_events table (event_store.py creates via SQLAlchemy)
--   - summaries table (summary_store.py creates if not exists)
--
-- =============================================================================

-- Create checkpoints database if it doesn't exist
SELECT 'CREATE DATABASE aiq_checkpoints' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiq_checkpoints')\gexec

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE aiq_jobs TO aiq;
GRANT ALL PRIVILEGES ON DATABASE aiq_checkpoints TO aiq;

-- =============================================================================
-- Create tables in aiq_jobs database
-- =============================================================================
\connect aiq_jobs

-- Job metadata table (NAT JobStore)
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

CREATE INDEX IF NOT EXISTS idx_job_info_status ON job_info(status);
CREATE INDEX IF NOT EXISTS idx_job_info_created_at ON job_info(created_at);

-- Job events table (SSE streaming, event persistence)
CREATE TABLE IF NOT EXISTS job_events (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    event_data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);
CREATE INDEX IF NOT EXISTS idx_job_events_job_id_id ON job_events(job_id, id);

-- Document summaries table
CREATE TABLE IF NOT EXISTS summaries (
    collection VARCHAR(256) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    summary TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (collection, filename)
);

CREATE INDEX IF NOT EXISTS idx_summaries_collection ON summaries(collection);

-- =============================================================================
-- Create LangGraph checkpoint tables in aiq_checkpoints database
-- These must exist before backends connect. Previously left to the app,
-- but if postgres restarts without a backend restart, the tables are lost
-- and running backends crash with "relation checkpoints does not exist".
-- =============================================================================
\connect aiq_checkpoints

CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
