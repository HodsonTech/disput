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

# Matches a model's own <answer>...</answer> block - models are silently
# instructed (see app.py's per-call system-prompt note) to wrap their
# current best answer in one of these once they have one, so it can be
# pulled out and shown clearly instead of making the user hunt for it
# through several turns of back-and-forth.
ANSWER_PATTERN = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)

# A model's own signal that it has nothing more to add (see app.py's
# per-call system-prompt note). Unlike <answer>, this is pure metadata -
# safe to strip out of `final` entirely rather than just extracted, since
# it's never the substantive content of a reply.
DONE_PATTERN = re.compile(r"\[DONE\]", re.IGNORECASE)

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
    # The openai SDK refuses to construct a client at all with an empty
    # api_key ("Missing credentials"), even though plenty of local
    # OpenAI-compatible servers don't check it. A source is allowed to have
    # a blank key (the setup form doesn't require one) - fall back to a
    # placeholder so that's still a valid, working configuration.
    return OpenAI(base_url=base_url, api_key=api_key or "not-needed")


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
    answer: str | None = None
    done: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# Generous on purpose - local/CPU inference and heavy "thinking" models can
# legitimately take minutes for one reply. This exists purely as an upper
# bound so a genuinely stuck backend eventually surfaces as an error
# instead of blocking forever - confirmed the hard way: with no timeout at
# all, a slow remote call left ctrl+q unable to actually terminate the
# process, since Python won't exit while a thread-pool worker is still
# blocked on it, however long that takes.
DEFAULT_TIMEOUT_SECONDS = 300.0


def call_model(
    client: OpenAI,
    cfg: ModelConfig,
    history: list[dict],
    temperature: float = 0.7,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ModelReply:
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
        extra_body["session_id"] = f"disput-{cfg.label}"

    resp = client.chat.completions.create(
        model=cfg.model,
        messages=messages,
        temperature=temperature,
        extra_body=extra_body or None,
        timeout=timeout,
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

    # Deliberately NOT stripped out of `final`: that string also becomes
    # this turn's entry in both models' ongoing conversation history, and
    # removing the tag risks leaving an empty message there if a reply was
    # nothing but an answer block - this is just an extracted copy for the
    # UI to surface prominently, not a replacement for the real text.
    answer_match = ANSWER_PATTERN.search(final)
    answer = answer_match.group(1).strip() if answer_match else None

    done = bool(DONE_PATTERN.search(final))
    if done:
        final = DONE_PATTERN.sub("", final).strip()

    # Not every OpenAI-compatible backend actually populates this (or the
    # response could theoretically lack it) - default to 0 rather than
    # letting a missing field blow up the whole call.
    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)

    return ModelReply(
        thinking=thinking,
        final=final,
        code_blocks=code_blocks,
        answer=answer,
        done=done,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


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
