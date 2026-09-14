# Disput

## What this is

A TUI (Textual) that puts two independently-hosted, OpenAI-API-compatible
LLMs into a live, turn-based dialogue with each other - no copy/paste
between them. Models sanity-check and critique each other rather than one
deferring to the other just because it's bigger, and can converge on and
write code together (fenced code blocks in a reply are auto-extracted to
disk). Originally built around a small 2B model debating a larger local
model (currently either a dense ~27B or an MoE ~26B-A4B), but the source/
model pickers are fully generic - any OpenAI-compatible endpoint works.

**File location:** the git repo is named `disput`; the local working
directory's name predates the rename and was left as-is deliberately -
renaming it would have disrupted the running session's working-directory
tracking.

**Real infra details** (actual hostnames/ports for the pre-seeded sources)
live in `PRIVATE_NOTES.md`, which is gitignored and never leaves this
machine - this file only describes things generically.

## Origin

Built to let on-prem LLMs reach **consensus** with each other rather than
trust either one unsupervised - a second, independently-reasoning model as
a check against hallucination and drift, not a bigger model assumed correct
by default. (Consensus, not quorum: quorum is about clearing a minimum
headcount before a vote counts; with exactly two participants there's no
threshold to clear, the actual goal is the two of them converging on the
same answer independently.)

The original pairing was `MiniCPM5-2B` against `Qwen3.8-27B`; `Gemma-4-26B-
A4B` (MoE) later replaced Qwen as the larger model - same role, noticeably
faster inference. The two also ran on genuinely different hardware from the
start: the 2B on a Windows PC with an RTX 5080, the 27B/26B-A4B on a Mac
with 48GB of RAM - deliberately disparate models on disparate hardware, not
just two instances of the same weights. Whether that disparity actually
makes hallucination/drift easier to catch (versus just producing two models
disagreeing for unrelated reasons) is still an open question - extensive
testing is needed here, this isn't a settled result.

## Layout

- `main.py` - entry point (`python3 main.py`), no install required.
- `disput/config.py` - saved source presets (name/base_url/api_key/
  enabled_tools), persisted at `~/.disput/presets.json` - **outside the
  repo on purpose**, so API keys can never end up committed, even
  accidentally, once this repo goes public.
- `disput/client.py` - `list_models()` (queries `/v1/models` live for the
  source picker), `call_model()` (reasoning-trace splitting, same dual
  handling as before: a `reasoning_content` field OR inline
  `<think>...</think>` tags), and code-block extraction/saving.
- `disput/app.py` - the Textual app: `SourceSetupScreen` (pick/add a
  source -> fetch its models -> pick one -> label + system prompt; run once
  per side), `TopicScreen`, `DialogueScreen` (the live turn loop).
- `pyproject.toml` - `pip install -e .` gives a `disput` console script.
- `presets.example.json` - documentation only, never read at runtime.
- `dialogue_output/` and `transcripts/` - generated at runtime, gitignored.
- Legacy artifacts from the old two-script version
  (`dialogue_transcript_gemma.md`, `reasoning_feed_gemma.log`) are still on
  disk but gitignored - kept as prior session data, not part of the tool.

## Backend / infra

- Sources are pure OpenAI-compatible endpoints (`base_url` + `api_key`),
  typically served locally via **Unsloth Desktop**, which exposes each
  loaded model on its own port (`/v1/chat/completions`, `/v1/models`, auth
  via `Authorization: Bearer <key>`).
- Two sources are pre-seeded in `~/.disput/presets.json` from the prior
  setup: a remote 2B model on a separate Windows PC (reachable over the
  public internet via a NAT port-forward, deliberately plain HTTP rather
  than HTTPS for a threat model where that's an acceptable tradeoff), and a
  larger local model served by Unsloth Desktop on the Mac running the
  script. See `PRIVATE_NOTES.md` (gitignored, local-only) for the actual
  hostnames/ports - not repeated here since this file is meant to be safe
  to make public.
- Unsloth's server-side tools (`python`, `terminal`, `web_search`) are wired
  through per-source `enabled_tools`, sent via `extra_body` fields
  (`enable_tools`, `enabled_tools`, `session_id`) since they're not part of
  the standard OpenAI schema. **Not yet verified**: whether `call_model()`'s
  response parsing needs adjusting when a tool call actually fires
  mid-conversation - this hasn't been stress-tested.

## How the conversation loop works

- Each model keeps its OWN view of history (its own turns as `assistant`,
  the other model's turns as `user`) - not a single shared transcript
  object.
- **Reasoning traces** are shown in a collapsible panel per turn in the TUI
  and written to `transcripts/disput_<session>_reasoning.log`, but are
  deliberately **NOT** fed into either model's ongoing conversation history -
  scratch space, not something the other model should treat as "said."
- **Round count is dynamic.** Set at setup (default 6); when reached, the
  dialogue pauses and the same moderator input box doubles as an "extend by
  how many more?" prompt - type a number to extend, anything else to stop.
- **Moderator injection**: the moderator input box is live throughout the
  run (not a timed window like the old scripts) - type a note and press
  Enter any time to inject it into both models' history as
  `[Moderator note]: ...` without stopping the loop.
- **Code extraction**: any fenced code block in a reply is pulled out and
  saved to `dialogue_output/<session>/turn_NN_<label>_<i>.<ext>`, language
  guessed from the fence tag.
- Transcript is written continuously (not just at the end) to
  `transcripts/disput_<session>.md`, each turn's reasoning wrapped in a
  collapsible `<details><summary>🧠 Thinking</summary>` block.

## Known open items

- Tool-call response parsing (see above) is unverified in practice.
- The Textual thread-worker turn loop assumes a real terminal; no
  non-interactive/headless mode exists (nor is one needed for this use case).

## Notable non-technical context

Gemma has an unprompted "Top Gun" persona easter egg - saying "talk to me,
Goose" flips it into a full Maverick/Goose call-and-response bit that
persists across unrelated follow-up questions (tested: it stayed in
character even answering a real weather query). Fun to show off in demos
alongside the actual dual-model debate mechanic.
