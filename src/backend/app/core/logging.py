import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = secrets or []

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        payload = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        for name in ("request_id", "job_id"):
            if hasattr(record, name):
                payload[name] = str(getattr(record, name))
        return json.dumps(payload)


def configure_logging(secrets: list[str]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(secrets))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
