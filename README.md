# Disputatio

Put two independently-hosted, OpenAI-API-compatible models into a live,
turn-based dialogue with each other - no copy/paste between them. They
critique and sanity-check each other rather than one deferring just because
it's bigger, and can converge on and write code together. Runs as a
full-screen terminal interface, not a script you re-run with different flags.

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
disputatio          # if installed via -e .
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

- `disputatio/config.py` - saved source presets, stored at
  `~/.disputatio/presets.json` (outside the repo, deliberately - so API keys
  never end up in git even once this repo goes public).
- `disputatio/client.py` - talking to a model, splitting out its reasoning
  trace, extracting fenced code blocks.
- `disputatio/app.py` - the Textual TUI: the setup wizard and the live
  dialogue screen.
- `dialogue_output/` and `transcripts/` are generated at runtime and
  gitignored.

## Backend notes

Built against [Unsloth Desktop](https://unsloth.ai), which exposes each
loaded local model on its own port via an OpenAI-compatible API
(`/v1/chat/completions`, `/v1/models`). Any other OpenAI-API-compatible
server works the same way - Disputatio only assumes the standard schema plus
optional `reasoning_content` / inline `<think>` tags for reasoning traces.
