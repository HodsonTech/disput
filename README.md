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
- **Model A and Model B aren't interchangeable slots.** Turn order is fixed:
  A always goes first each turn (it sees the bare topic with no other input
  yet), B always goes second (reacting to A's prior turn). For a topic that
  assigns asymmetric roles ("one of you propose, the other critique"), A
  ends up the proposer and B the chaperone/critic by default - the setup
  screen for each side says so up front (and as a hover tooltip on its
  title), so you can pick which real model goes in which seat on purpose.
- Each source's `/v1/models` is queried live and shown as a pickable list, so
  you always select from what's actually loaded right now rather than typing
  a model id from memory.
- Set a display label and system prompt per model (defaults are pre-filled
  and editable), then a starting topic and a turn count - extendable
  mid-run rather than something you have to guess up front.
- Watch the dialogue live: each turn renders as it comes in, with any
  `<think>...</think>` / `reasoning_content` trace tucked into a collapsible
  panel so it doesn't clutter the read but is there if you want it.
- A pinned **Current Answer** panel above the log: models often converge on
  a real answer well before the turn limit, then spend several more turns
  just agreeing with each other before the run actually ends. Both are
  silently told to wrap their current best answer in `<answer>...</answer>`
  whenever they have one - they can keep discussing after, and post an
  updated one later if it's refined. The panel always shows the latest one,
  so you don't have to read through the back-and-forth to find it.
- **Stops the self-congratulation loop early**: if both models independently
  signal they genuinely have nothing more to add, the dialogue pauses with
  the same extend-or-stop prompt used at the turn limit - instead of
  grinding through the rest of a turn count set up front just to agree with
  each other some more. Requires *both* sides to agree, not just one, and
  never quits on its own either way.
- Type into the moderator box at any time to inject a note into both models'
  history without stopping the conversation.
- Any fenced code block either model writes is automatically saved to
  `dialogue_output/<session>/` as its own file, in addition to appearing in
  the transcript.
- A full Markdown transcript and a raw reasoning log are written to
  `transcripts/` continuously as the conversation runs.

## Setup

Requires Python 3.10+.

### macOS

```bash
git clone https://github.com/HodsonTech/disput.git
cd disput
python3 -m pip install -e .
disput
```

That's it - macOS's Python (from python.org, Homebrew, or MacPorts) installs
packages directly with no extra steps.

### Debian / Ubuntu (and derivatives, e.g. in a VM)

Newer Debian/Ubuntu refuse a plain `pip install` outside a virtual
environment (`error: externally-managed-environment`) - this is a guard rail
on their *system* Python specifically, not a Disput requirement, and not
something you'll hit on macOS. The cleanest way around it is
[`pipx`](https://pipx.pypa.io), which creates that isolated environment for
you automatically but still puts the `disput` command on your normal PATH,
so it survives reboots and new terminals with nothing more to remember:

```bash
sudo apt update && sudo apt install pipx git
git clone https://github.com/HodsonTech/disput.git
cd disput
pipx install -e .
pipx ensurepath
disput
```

That `pipx ensurepath` line matters: `pipx install` puts the `disput`
command in `~/.local/bin`, but on a fresh system that folder usually isn't
on your PATH yet - so the install succeeds, pipx prints a warning about it,
and `disput` silently does nothing when you type it (your shell can't find
it, but doesn't say so). `pipx ensurepath` fixes your PATH for you (usually
by editing `~/.bashrc`). **Close and reopen your terminal after running
it** - the fix doesn't apply to the shell session you ran it in, only new
ones. Then `disput` should resolve normally.

If it still doesn't, check the two things that command fixes:
```bash
ls ~/.local/bin/disput            # did pipx actually put it there?
echo $PATH | tr ':' '\n' | grep local/bin   # is that folder on your PATH?
```

If you'd rather not install `pipx`, a plain venv works too, but you have to
manually reactivate it in every new shell (including after a reboot) before
`disput` will be found:

```bash
sudo apt install python3-venv git   # if this fails, apt will tell you the
                                    # exact versioned package name to use,
                                    # e.g. python3.13-venv - use that instead
git clone https://github.com/HodsonTech/disput.git
cd disput
python3 -m venv .venv
source .venv/bin/activate   # <- repeat this line in every new terminal
python3 -m pip install -e .
disput
```

Do **not** use `pip install --break-system-packages` to skip this - it
works, but risks silently conflicting with apt-managed packages later for
no real benefit over `pipx`.

### No install at all

```bash
python3 -m pip install openai textual   # or pipx equivalent on Debian/Ubuntu
python3 main.py
```

## Run

```bash
disput          # if installed via -e . / pipx
# or
python3 main.py     # no install needed
```

You'll be walked through: source + model for Model A -> source + model for
Model B -> topic + turn count -> live dialogue.

**Keys during the dialogue:**
- `ctrl+p` - pause/resume
- `ctrl+g` - abort the current in-flight turn (e.g. it's hanging/stalled)
- `ctrl+n` - start a fresh topic with the same two models, no re-setup
- `esc` - after an error, reopen setup for whichever model broke
- `ctrl+q` - quit and save

Type in the moderator box + Enter any time to inject a note without
stopping the conversation. When the turn limit is hit, type a number there
to extend by that many turns, or `stop` (or just Enter) to wrap up without
quitting the app.

## Where things live

- `disput/config.py` - saved source presets, stored at
  `~/.disput/presets.json` (outside the repo, deliberately - so API keys
  never end up in git even once this repo goes public).
- `disput/client.py` - talking to a model, splitting out its reasoning
  trace, extracting fenced code blocks.
- `disput/app.py` - the Textual TUI: the setup wizard and the live
  dialogue screen.
- `dialogue_output/` and `transcripts/` are generated at runtime and
  gitignored - **relative to whatever directory you were in when you ran
  `disput`**, not a fixed location. This matters more than it sounds: a
  `pipx`/`pip install -e .` install puts `disput` on your PATH globally, so
  it's runnable from anywhere - run it from your home directory instead of
  the repo folder and that's where these two folders show up. If you can't
  find a transcript, check where you actually launched it from, e.g.
  `find ~ -maxdepth 4 -name transcripts -type d`.

## Backend notes

Built against [Unsloth Desktop](https://unsloth.ai), which exposes each
loaded local model on its own port via an OpenAI-compatible API
(`/v1/chat/completions`, `/v1/models`). Any other OpenAI-API-compatible
server works the same way - Disput only assumes the standard schema plus
optional `reasoning_content` / inline `<think>` tags for reasoning traces.
