"""Persistent storage for saved model sources (endpoint + key + default tools).

Lives outside the repo entirely (``~/.disput/presets.json``) so API keys
never end up in a directory that gets git-committed or, later, made public.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".disput"
PRESETS_PATH = CONFIG_DIR / "presets.json"


@dataclass
class Source:
    name: str
    base_url: str
    api_key: str
    enabled_tools: list[str] = field(default_factory=list)


def load_sources() -> list[Source]:
    if not PRESETS_PATH.exists():
        return []
    data = json.loads(PRESETS_PATH.read_text())
    return [Source(**s) for s in data.get("sources", [])]


def save_sources(sources: list[Source]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PRESETS_PATH.write_text(json.dumps({"sources": [asdict(s) for s in sources]}, indent=2))


def upsert_source(source: Source, old_name: str | None = None) -> None:
    """Add a new source, or overwrite an existing one with the same name.

    Pass `old_name` when editing a source that may have been renamed, so the
    entry under its previous name is removed instead of left behind as a
    stale duplicate.
    """
    sources = load_sources()
    names_to_drop = {source.name}
    if old_name:
        names_to_drop.add(old_name)
    sources = [s for s in sources if s.name not in names_to_drop]
    sources.append(source)
    save_sources(sources)


def delete_source(name: str) -> None:
    """Remove a saved source by name. No-op if it's already gone."""
    sources = [s for s in load_sources() if s.name != name]
    save_sources(sources)
