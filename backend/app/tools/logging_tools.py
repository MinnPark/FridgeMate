from typing import Any


def append_log(
    logs: list[dict[str, Any]] | None,
    *,
    node: str,
    event: str,
    **payload: Any,
) -> list[dict[str, Any]]:
    next_logs = list(logs or [])
    next_logs.append({"node": node, "event": event, **payload})
    return next_logs
