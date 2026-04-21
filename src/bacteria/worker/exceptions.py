class PermanentFailure(Exception):
    """Raised by a node to signal that a job should not be retried."""
