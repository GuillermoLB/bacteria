from bacteria.observability.logging import setup_logging


def setup_observability(app=None) -> None:
    from bacteria.settings import get_settings
    obs = get_settings().observability

    setup_logging(level=obs.log_level, fmt=obs.log_format)

    if app is not None and obs.otel_endpoint:
        from bacteria.observability.tracing import setup_otel
        setup_otel(endpoint=obs.otel_endpoint, app=app)
