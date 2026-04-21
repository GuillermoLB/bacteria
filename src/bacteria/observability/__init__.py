from bacteria.observability.logging import setup_logging
from bacteria.observability.sentry import setup_sentry
from bacteria.observability.langfuse import setup_langfuse


def setup_observability(app=None) -> None:
    from bacteria.settings import get_settings
    obs = get_settings().observability

    setup_logging(level=obs.log_level, fmt=obs.log_format)

    if obs.sentry_dsn:
        setup_sentry(dsn=obs.sentry_dsn, environment=obs.sentry_environment)

    if obs.langfuse_secret_key and obs.langfuse_public_key:
        setup_langfuse(
            secret_key=obs.langfuse_secret_key,
            public_key=obs.langfuse_public_key,
            host=obs.langfuse_host,
        )

    if app is not None and obs.otel_endpoint:
        from bacteria.observability.tracing import setup_otel
        setup_otel(endpoint=obs.otel_endpoint, app=app)
