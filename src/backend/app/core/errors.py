class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.retry_after = retry_after
        self.details = details or []
