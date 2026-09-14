"""Model I/O: talking to an OpenAI-API-compatible endpoint and pulling apart
its response into a final answer, an optional reasoning trace, and any code
blocks worth saving to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

# Matches inline <think>...</think> blocks that some backends (raw
# llama.cpp/llama-server) embed directly in the content string rather than
# exposing as a separate response field.
THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)

# ```lang\n...code...\n``` fenced blocks, used both for display and for
# extraction to disk.
CODE_FENCE_PATTERN = re.compile(r"```([a-zA-Z0-9_+\-]*)\n(.*?)```", re.DOTALL)

# Best-effort language -> file extension map for extracted code blocks.
# Anything not listed here falls back to .txt.
LANG_EXT = {
    "python": "py", "py": "py",
    "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts",
    "bash": "sh", "sh": "sh", "shell": "sh", "zsh": "sh",
    "json": "json",
    "yaml": "yaml", "yml": "yaml",
    "html": "html",
    "css": "css",
    "c": "c",
    "cpp": "cpp", "c++": "cpp",
    "java": "java",
    "go": "go",
    "rust": "rs", "rs": "rs",
    "ruby": "rb", "rb": "rb",
    "sql": "sql",
    "markdown": "md", "md": "md",
    "toml": "toml",
}


def make_client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


def list_models(base_url: str, api_key: str) -> list[str]:
    """Query the endpoint's /v1/models and return the model ids it reports.

    Raises whatever the openai client raises (connection errors, auth
    errors, etc.) - callers are expected to surface that to the user rather
    than silently swallow it, since a source that can't be reached is
    exactly what someone picking a source needs to know about.
    """
    client = make_client(base_url, api_key)
    resp = client.models.list()
    return sorted(m.id for m in resp.data)


@dataclass
class ModelConfig:
    label: str
    base_url: str
    api_key: str
    model: str
    system_prompt: str
    enabled_tools: list[str] = field(default_factory=list)


@dataclass
class ModelReply:
    thinking: str | None
    final: str
    code_blocks: list[tuple[str, str]]  # (language, code)


def call_model(client: OpenAI, cfg: ModelConfig, history: list[dict], temperature: float = 0.7) -> ModelReply:
    """history is a list of {'role': 'user'/'assistant', 'content': str} from
    THIS model's point of view (its own prior turns are 'assistant', the
    other model's turns come in as 'user')."""
    messages = [{"role": "system", "content": cfg.system_prompt}] + history

    # Unsloth's server-side tools (python/web_search/terminal) aren't part of
    # the standard OpenAI schema, so they have to go through extra_body - the
    # openai client's catch-all for passing vendor-specific fields straight
    # through in the JSON request body.
    extra_body = {}
    if cfg.enabled_tools:
        extra_body["enable_tools"] = True
        extra_body["enabled_tools"] = cfg.enabled_tools
        extra_body["session_id"] = f"disputatio-{cfg.label}"

    resp = client.chat.completions.create(
        model=cfg.model,
        messages=messages,
        temperature=temperature,
        extra_body=extra_body or None,
    )
    message = resp.choices[0].message
    raw_content = (message.content or "").strip()

    # Some backends (vLLM/DeepSeek-style reasoning APIs) put the reasoning
    # trace in its own field. Others (raw llama.cpp/llama-server) just embed
    # <think>...</think> inline in the content string. Handle both.
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        thinking, final = reasoning.strip(), raw_content
    else:
        match = THINK_PATTERN.search(raw_content)
        if match:
            thinking = match.group(1).strip()
            final = THINK_PATTERN.sub("", raw_content).strip()
        else:
            thinking, final = None, raw_content

    code_blocks = [(lang.strip().lower(), code.strip()) for lang, code in CODE_FENCE_PATTERN.findall(final)]

    return ModelReply(thinking=thinking, final=final, code_blocks=code_blocks)


def save_code_blocks(code_blocks: list[tuple[str, str]], out_dir: Path, turn: int, label: str) -> list[Path]:
    """Writes each code block to its own file under out_dir, named by turn
    number, speaker label, and index. Returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)
    written = []
    for i, (lang, code) in enumerate(code_blocks, start=1):
        ext = LANG_EXT.get(lang, "txt")
        path = out_dir / f"turn_{turn:02d}_{safe_label}_{i}.{ext}"
        path.write_text(code + "\n")
        written.append(path)
    return written
