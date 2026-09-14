"""Persistent storage for saved model sources (endpoint + key + default tools).

Lives outside the repo entirely (``~/.dialectic/presets.json``) so API keys
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


def upsert_source(source: Source) -> None:
    """Add a new source, or overwrite the existing one with the same name."""
    sources = load_sources()
    sources = [s for s in sources if s.name != source.name]
    sources.append(source)
    save_sources(sources)
