from bacteria.observability.logging import setup_logging


def setup_observability(app=None) -> None:
    from bacteria.settings import get_settings
    obs = get_settings().observability

    setup_logging(level=obs.log_level, fmt=obs.log_format)

    from bacteria.observability.tracing import instrument_app, setup_tracing
    setup_tracing(otlp_endpoint=obs.otel_endpoint, console=obs.otel_console)

    if app is not None:
        instrument_app(app)
