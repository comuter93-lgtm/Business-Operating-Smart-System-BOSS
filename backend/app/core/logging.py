import json
import logging
import re
from datetime import datetime, timezone


_SECRET_KEYS = ("password", "pin", "secret", "token", "otp", "authorization", "cookie")


def mask_sensitive(data: dict) -> dict:
    masked = {}
    for k, v in data.items():
        if any(sk in k.lower() for sk in _SECRET_KEYS):
            masked[k] = "***REDACTED***"
        elif isinstance(v, dict):
            masked[k] = mask_sensitive(v)
        else:
            masked[k] = v
    return masked


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": re.sub(r"(Bearer\s+)[A-Za-z0-9\-_\.]+", r"\1***", record.getMessage()),
        }
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload["extra"] = mask_sensitive(record.extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str = "boss") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

