# Disput

Put two independently-hosted, OpenAI-API-compatible models into a live,
turn-based dialogue with each other - no copy/paste between them. They
critique and sanity-check each other rather than one deferring just because
it's bigger, and can converge on and write code together. Runs as a
full-screen terminal interface, not a script you re-run with different flags.

## Why

Built to let on-prem LLMs reach **consensus** with each other rather than
trust either one unsupervised - a second, independently-reasoning model as
a check against hallucination and drift, not a bigger model assumed correct
by default.

The original pairing was a 2B model (`MiniCPM5-2B`) against a 27B model
(`Qwen3.8-27B`), later swapped for a 26B-A4B MoE model (`Gemma-4-26B-A4B`)
in the larger seat for noticeably faster inference. The two also ran on
genuinely different hardware from the start - one on a PC with an RTX 5080,
the other on a Mac with 48GB of RAM - deliberately disparate models on
disparate hardware, not two instances of the same weights. Whether that
disparity actually makes hallucination and drift easier to catch, versus
just producing two models that disagree for unrelated reasons, is still an
open question worth testing more, not a settled result.

## What it does

- Interactively pick (or add) a **source** - an OpenAI-compatible endpoint
  (base URL + API key) - for each side of the conversation. Saved sources are
  remembered for next time.
- Each source's `/v1/models` is queried live and shown as a pickable list, so
  you always select from what's actually loaded right now rather than typing
  a model id from memory.
- Set a display label and system prompt per model (defaults are pre-filled
  and editable), then a starting topic and a turn count - extendable
  mid-run rather than something you have to guess up front.
- Watch the dialogue live: each turn renders as it comes in, with any
  `<think>...</think>` / `reasoning_content` trace tucked into a collapsible
  panel so it doesn't clutter the read but is there if you want it.
- Type into the moderator box at any time to inject a note into both models'
  history without stopping the conversation.
- Any fenced code block either model writes is automatically saved to
  `dialogue_output/<session>/` as its own file, in addition to appearing in
  the transcript.
- A full Markdown transcript and a raw reasoning log are written to
  `transcripts/` continuously as the conversation runs.

## Setup

```bash
python3 -m pip install -e .
```

(or just `python3 -m pip install openai textual` and run without installing.)

## Run

```bash
disput          # if installed via -e .
# or
python3 main.py     # no install needed
```

You'll be walked through: source + model for Model A -> source + model for
Model B -> topic + turn count -> live dialogue.

**Keys during the dialogue:** `ctrl+p` pause/resume, `ctrl+q` quit and save.
Type in the moderator box + Enter to inject a note; when the turn limit is
hit, type a number there to extend by that many turns, or anything else to
stop.

## Where things live

- `disput/config.py` - saved source presets, stored at
  `~/.disput/presets.json` (outside the repo, deliberately - so API keys
  never end up in git even once this repo goes public).
- `disput/client.py` - talking to a model, splitting out its reasoning
  trace, extracting fenced code blocks.
- `disput/app.py` - the Textual TUI: the setup wizard and the live
  dialogue screen.
- `dialogue_output/` and `transcripts/` are generated at runtime and
  gitignored.

## Backend notes

Built against [Unsloth Desktop](https://unsloth.ai), which exposes each
loaded local model on its own port via an OpenAI-compatible API
(`/v1/chat/completions`, `/v1/models`). Any other OpenAI-API-compatible
server works the same way - Disput only assumes the standard schema plus
optional `reasoning_content` / inline `<think>` tags for reasoning traces.
