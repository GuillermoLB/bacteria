_client = None


def setup_langfuse(secret_key: str, public_key: str, host: str) -> None:
    global _client
    from langfuse import Langfuse
    _client = Langfuse(secret_key=secret_key, public_key=public_key, host=host)


def get_client():
    return _client


def observe(func):
    """Decorator that traces a function with Langfuse if configured, no-op otherwise."""
    try:
        from langfuse.decorators import observe as _observe
        if _client is not None:
            return _observe(func)
    except ImportError:
        pass
    return func
