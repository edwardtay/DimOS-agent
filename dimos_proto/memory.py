"""Persistent agent memory across missions.

The agent can `remember(key, value)`, `recall(query)`, and `forget(key)`.
Backed by a single JSON file so memories survive process restarts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class AgentMemory:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.environ.get("DIMOS_MEMORY", "memory.json"))
        self._cache: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._cache, indent=2))
        except OSError:
            pass

    def remember(self, key: str, value: str) -> str:
        self._cache[str(key)] = str(value)
        self._save()
        return f"remembered '{key}'"

    def recall(self, query: str = "") -> dict[str, str]:
        if not query:
            return dict(self._cache)
        q = query.lower()
        return {k: v for k, v in self._cache.items()
                if q in k.lower() or q in v.lower()}

    def forget(self, key: str) -> str:
        if key in self._cache:
            del self._cache[key]
            self._save()
            return f"forgot '{key}'"
        return f"no memory of '{key}'"

    def all(self) -> dict[str, str]:
        return dict(self._cache)
