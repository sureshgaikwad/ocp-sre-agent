"""
Structured JSON logging utility.

All SRE agent components use this logger for consistent, parseable logs.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Optional
import uuid


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs as JSON.

    Standard fields:
    - timestamp: ISO 8601 timestamp
    - level: Log level (INFO, WARNING, ERROR, etc.)
    - logger: Logger name
    - message: Log message
    - request_id: Request ID for tracing (if provided)
    - resource_kind: Kubernetes resource kind (if provided)
    - action_taken: Action performed (if provided)
    - Additional fields from 'extra' dict
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add standard SRE agent fields if present
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "resource_kind"):
            log_data["resource_kind"] = record.resource_kind
        if hasattr(record, "action_taken"):
            log_data["action_taken"] = record.action_taken
        if hasattr(record, "namespace"):
            log_data["namespace"] = record.namespace
        if hasattr(record, "resource_name"):
            log_data["resource_name"] = record.resource_name

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any additional fields from 'extra'
        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName", "relativeCreated",
                "thread", "threadName", "exc_info", "exc_text", "stack_info",
                "request_id", "resource_kind", "action_taken", "namespace", "resource_name"
            ] and not key.startswith("_"):
                log_data[key] = value

        return json.dumps(log_data)


class SRELogger:
    """
    Structured logger for SRE agent components.

    Provides convenience methods for logging with standard fields.
    """

    def __init__(self, name: str, level: int = logging.INFO):
        """
        Initialize SRE logger.

        Args:
            name: Logger name (usually module name)
            level: Logging level (default: INFO)
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.logger.propagate = False  # Don't propagate to root logger

        # Remove existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # Add JSON handler to stdout
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

        self.request_id: Optional[str] = None

    def set_request_id(self, request_id: Optional[str] = None) -> str:
        """
        Set request ID for tracing.

        Args:
            request_id: Request ID (generates new UUID if None)

        Returns:
            The request ID
        """
        self.request_id = request_id or str(uuid.uuid4())
        return self.request_id

    def _build_extra(
        self,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Build extra dict for logging."""
        extra = {}
        if request_id or self.request_id:
            extra["request_id"] = request_id or self.request_id
        if resource_kind:
            extra["resource_kind"] = resource_kind
        if resource_name:
            extra["resource_name"] = resource_name
        if namespace:
            extra["namespace"] = namespace
        if action_taken:
            extra["action_taken"] = action_taken
        extra.update(kwargs)
        return extra

    def info(
        self,
        message: str,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log info message."""
        extra = self._build_extra(
            request_id, resource_kind, resource_name, namespace, action_taken, **kwargs
        )
        self.logger.info(message, extra=extra)

    def warning(
        self,
        message: str,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log warning message."""
        extra = self._build_extra(
            request_id, resource_kind, resource_name, namespace, action_taken, **kwargs
        )
        self.logger.warning(message, extra=extra)

    def error(
        self,
        message: str,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        exc_info: bool = False,
        **kwargs
    ) -> None:
        """Log error message."""
        extra = self._build_extra(
            request_id, resource_kind, resource_name, namespace, action_taken, **kwargs
        )
        self.logger.error(message, extra=extra, exc_info=exc_info)

    def debug(
        self,
        message: str,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log debug message."""
        extra = self._build_extra(
            request_id, resource_kind, resource_name, namespace, action_taken, **kwargs
        )
        self.logger.debug(message, extra=extra)

    def critical(
        self,
        message: str,
        request_id: Optional[str] = None,
        resource_kind: Optional[str] = None,
        resource_name: Optional[str] = None,
        namespace: Optional[str] = None,
        action_taken: Optional[str] = None,
        exc_info: bool = False,
        **kwargs
    ) -> None:
        """Log critical message."""
        extra = self._build_extra(
            request_id, resource_kind, resource_name, namespace, action_taken, **kwargs
        )
        self.logger.critical(message, extra=extra, exc_info=exc_info)


def get_logger(name: str, level: int = logging.INFO) -> SRELogger:
    """
    Get or create an SRE logger.

    Args:
        name: Logger name (usually __name__)
        level: Logging level

    Returns:
        SRELogger instance
    """
    return SRELogger(name, level)


if __name__ == "__main__":
    # Demo
    logger = get_logger("demo")
    logger.set_request_id("req-12345")

    logger.info(
        "Pod logs fetched successfully",
        resource_kind="Pod",
        resource_name="my-pod",
        namespace="default",
        action_taken="fetch_logs",
        log_lines=150
    )

    logger.warning(
        "Pod is in CrashLoopBackOff",
        resource_kind="Pod",
        resource_name="failing-pod",
        namespace="openshift-pipelines",
        restart_count=5
    )

    logger.error(
        "Failed to call MCP tool",
        action_taken="mcp_call",
        tool_name="pods_log",
        error_code="timeout"
    )
