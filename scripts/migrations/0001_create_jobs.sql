CREATE TABLE IF NOT EXISTS jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue         TEXT NOT NULL DEFAULT 'default',
    payload       JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    priority      INT DEFAULT 0,
    attempts      INT DEFAULT 0,
    max_attempts  INT DEFAULT 3,
    scheduled_at  TIMESTAMPTZ,
    claimed_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    failed_at     TIMESTAMPTZ,
    result        JSONB,
    error         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs (status, priority DESC, created_at ASC)
    WHERE status = 'pending';
