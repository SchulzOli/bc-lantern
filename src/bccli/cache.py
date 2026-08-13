from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from bccli.json_io import write_json_atomic

CacheValue = dict[str, Any]


class CacheStore(Protocol):
    def get(self, namespace: str, key: str) -> CacheValue | None: ...

    def put(self, namespace: str, key: str, value: CacheValue) -> None: ...

    def delete(self, namespace: str, key: str) -> None: ...


class JsonCacheStore:
    """Small reusable JSON cache, partitioned by feature namespace and key."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, namespace: str, key: str) -> CacheValue | None:
        path = self._path(namespace, key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def put(self, namespace: str, key: str, value: CacheValue) -> None:
        write_json_atomic(self._path(namespace, key), value)

    def delete(self, namespace: str, key: str) -> None:
        self._path(namespace, key).unlink(missing_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        namespace_parts = [self._safe(part) for part in namespace.split("/") if part]
        return self.root.joinpath(*namespace_parts, f"{self._safe(key)}.json")

    @staticmethod
    def _safe(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
        return normalized or "default"
