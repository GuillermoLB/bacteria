from prometheus_client import Counter, Gauge, Histogram

jobs_enqueued = Counter(
    "bacteria_jobs_enqueued_total",
    "Jobs enqueued since startup",
    ["queue", "event_type"],
)

jobs_completed = Counter(
    "bacteria_jobs_completed_total",
    "Jobs completed successfully",
    ["queue", "event_type"],
)

jobs_failed = Counter(
    "bacteria_jobs_failed_total",
    "Jobs failed",
    ["queue", "event_type", "permanent"],
)

job_duration = Histogram(
    "bacteria_job_duration_seconds",
    "End-to-end job execution time",
    ["queue", "event_type"],
)

queue_depth = Gauge(
    "bacteria_queue_depth",
    "Current PENDING job count",
    ["queue"],
)

worker_active = Gauge(
    "bacteria_worker_active",
    "Number of currently executing workers",
)

agent_tokens = Counter(
    "bacteria_agent_tokens_total",
    "LLM tokens used",
    ["provider", "model", "token_type"],
)

agent_duration = Histogram(
    "bacteria_agent_duration_seconds",
    "Agent run duration",
    ["provider", "model"],
)
