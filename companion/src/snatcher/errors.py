class SnatcherError(Exception):
    """A user-facing, classified pipeline error."""

    def __init__(self, message: str, *, code: str = "pipeline_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CancelledError(SnatcherError):
    def __init__(self) -> None:
        super().__init__("Capture cancelled.", code="cancelled", retryable=False)
