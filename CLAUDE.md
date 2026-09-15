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
  `<think>...</think>` tags), and `save_final_answer_code()` (extracts code
  from the final answer only - see "Code extraction" below).
- `disput/app.py` - the Textual app: `SourceSetupScreen` (pick/add a
  source -> fetch its models -> pick one -> label + system prompt; run once
  per side), `TopicScreen`, `DialogueScreen` (the live turn loop).
- `pyproject.toml` - `pip install -e .` gives a `disput` console script.
- `presets.example.json` - documentation only, never read at runtime.
- `TRANSCRIPTS_DIR` / `OUTPUT_DIR` in `app.py` - fixed at `Path.home() /
  "Transcripts"` and `.../Transcripts/dialogue_output`, NOT CWD-relative.
  Used to be `Path("transcripts")`/`Path("dialogue_output")` - harmless
  when always run via `python3 main.py` from inside the repo, but a
  `pipx`/`pip install -e .` install puts `disput` on PATH globally, so
  it's genuinely runnable from anywhere - output was landing wherever the
  user happened to be standing, not somewhere predictable. Since both
  constants are evaluated at **import time**, every test that runs a real
  dialogue turn writes through them - all 25 test scripts redirect `HOME`
  to a fresh temp dir before importing `disput.app`, rather than patching
  each test's `TRANSCRIPTS_DIR`/`OUTPUT_DIR` individually.
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
- **Turn order is fixed and asymmetric, not cosmetic.** `self.current = "A"`
  at init and `take_turn()` always starts there: Model A's first call sees
  nothing but the bare topic (`history_a` seeded with just `{"role": "user",
  "content": topic}`), Model B's first call already has A's opening reply
  sitting in `history_b` as a `user` message. For any topic that assigns
  asymmetric roles ("one of you propose, the other critique"), A becomes
  the proposer and B the chaperone/critic by pure mechanical consequence of
  going second - not because either model is told to play that role. Made
  visible in `SourceSetupScreen._role_hint_text()` (shown once on the
  source-picking step, plus as a `Static.tooltip` on the persistent title)
  since it was previously invisible anywhere in the app and genuinely
  surprised a user who assumed the topic's "one of you / the other" framing
  was left entirely up to the models to sort out themselves.
- **"Already used by the other side" marker**: `SourceSetupScreen` takes an
  optional `other_cfg: ModelConfig | None` - the other side's already-chosen
  config, passed whenever it's known (`_got_a` setting up B, or
  `action_fix_broken_model`'s error recovery, which knows both sides
  regardless of which one broke). `show_source_step()` appends `"  ★ Model
  {other_side} is using this"` to any source whose `base_url` matches;
  `show_model_step()` does the same by `base_url` + exact model id. Purely
  a display suffix on the `Option` prompt - the underlying `id` used for
  selection (`src-{i}` / the raw model id) is untouched. Previously gave no
  indication at all that a source/model was already in use by the other side.
- **Reasoning traces** are shown in a collapsible panel per turn in the TUI
  and written to `~/Transcripts/disput_<session>_reasoning.log`, but are
  deliberately **NOT** fed into either model's ongoing conversation history -
  scratch space, not something the other model should treat as "said."
- **Silent per-call system-prompt injection**: `take_turn()` appends three
  notes to `cfg.system_prompt` for that call only (never touching the real
  `cfg_a`/`cfg_b`, never shown in the transcript/log):
  - a turn-budget note ("turn N of TOTAL, M remaining, pace yourself") so
    neither model is guessing how much runway is left, recomputed fresh
    every turn so it stays accurate across an extend;
  - an answer-tag note asking each model to wrap its current best answer in
    `<answer>...</answer>` once it has one (see below);
  - a `[DONE]` note asking each model to say so once it genuinely has
    nothing more to add (see mutual-convergence below).
- **Current Answer panel**: `client.py`'s `call_model()` extracts an
  `<answer>...</answer>` block into `ModelReply.answer` without stripping it
  out of `final` (stripping risked an empty history entry if a reply was
  nothing but an answer block). `DialogueScreen` pins the latest one in
  `#answer-panel` above the log - exists because models routinely converge
  on a real answer several turns before the limit, then spend the rest just
  agreeing with each other; this surfaces it without needing to read the
  whole back-and-forth.
  - `#answer-panel` is a `VerticalScroll` (not a plain `Static`), so it's
    independently scrollable and no longer needs truncation at all - `ctrl+f`
    (`action_toggle_answer_panel`) toggles its `.styles.height` between
    `ANSWER_PANEL_COMPACT_HEIGHT` (8) and `ANSWER_PANEL_EXPANDED_HEIGHT`
    (20) via `_apply_answer_panel_height()`.
  - That same method sizes it to `"auto"` while `_latest_answer is None` -
    giving it a fixed compact height even when empty ("No answer proposed
    yet.") reserved 8 rows for nothing and reproduced the topic-banner
    crush bug again (combined with the banner, log dropped to 2 visible
    rows on a huge topic) - caught by the existing `huge_topic_test`
    regression test, not by inspection.
  - Once the run pauses (turn limit or mutual convergence), the full answer
    is also auto-appended into `#log` itself via `_mount_final_answer_block()`
    as a `.final-answer`-classed block - so it's readable in the normal
    scrollback too, not just the panel. Guarded by
    `self._final_answer_mounted_for` (the turn_no already appended) so
    extending and re-triggering without a new answer doesn't duplicate it.
- **Mutual-convergence early stop**: unlike `<answer>`, a model's `[DONE]`
  signal is pure metadata (never the substantive content of a reply), so
  `call_model()` strips it out of `final` entirely rather than just
  extracting a copy - parsed into `ModelReply.done`. `DialogueScreen`
  tracks `self._converged = {"A": bool, "B": bool}`, updated to that side's
  `reply.done` on every one of its turns (so a stale "done" from many turns
  back can't combine with a fresh one - each flag reflects only that side's
  *most recent* turn). Only once **both** are `True` simultaneously does it
  do anything: resets both flags and reuses the exact same
  `awaiting_extend` prompt as hitting the turn limit. Deliberately requires
  both sides, not one - a single model declaring victory isn't trustworthy
  enough to cut a real discussion short, and reusing `awaiting_extend`
  means it inherits all of that path's existing safety (nothing here can
  silently quit the app either).
- **Round count is dynamic.** Set at setup (default 6); when reached, the
  dialogue pauses and the same moderator input box doubles as an "extend by
  how many more?" prompt. A number extends; `stop`/`q`/`quit`/`no`/empty
  settles into a finished-but-still-open state (a number can still be typed
  later to extend after all); anything else is just logged as a normal
  moderator note while still waiting for an actual decision. Nothing typed
  here ever quits the app on its own - `ctrl+q` is the only thing that does,
  precisely because a plain note used to trigger a silent full exit.
- **Moderator injection**: the moderator input box is live throughout the
  run - type a note and press Enter any time to inject it into both models'
  history as `[Moderator note]: ...` without stopping the loop.
- **Aborting a stuck turn**: `ctrl+g` closes the in-flight client's
  connection pool (best-effort - the sync openai client offers no cleaner
  cancellation lever) and rebuilds a fresh client for that side. `call_model`
  also carries a generous (5 min default) request timeout, added after a
  real incident: a slow remote call left `ctrl+q` unable to terminate the
  process at all, since Python won't exit while a thread-pool worker is
  still blocked on it. `ctrl+q` now also arms a daemon safety-net timer that
  force-terminates ~2s after the normal exit, regardless.
- **Recovering from a model error**: `escape` reopens the setup wizard
  scoped to whichever side broke (`SourceSetupScreen`, same as initial
  setup) and resumes the same turn once fixed - not a fresh dialogue.
- **Starting a fresh topic**: `ctrl+n` prompts for a new topic/turn count
  and pushes a brand-new `DialogueScreen` with the same `cfg_a`/`cfg_b` -
  clean history, its own transcript/reasoning/code-output files - rather
  than resetting the current screen in place or requiring a full restart.
- **Code extraction**: no longer per-turn. That used to save every fenced
  code block from every turn as its own `turn_NN_<label>_<i>.<ext>` file -
  a real user complaint: "some nonsense code that's meaningless," a pile of
  small, disconnected, out-of-context fragments with no coherent final
  result. Removed entirely (`ModelReply.code_blocks`, `save_code_blocks()`,
  the per-turn extraction in `handle_turn_result`). Replaced with
  `client.save_final_answer_code()`, called only from the save-choice flow
  below (`full`/`result` modes) - extracts code from `self._latest_answer`
  specifically, saved as `~/Transcripts/dialogue_output/<session>/answer_N.<ext>`. The
  final answer is the one thing actually worth having as a standalone file.
- **Save-choice flow**: typing `stop` at the `awaiting_extend` prompt no
  longer just idles - it sets `self._awaiting_save_choice = True` and shows
  `SAVE_CHOICE_PROMPT`. `_handle_save_choice()` dispatches: a bare number
  still extends immediately (equivalent to `cancel` + extending, in one
  step, so the old "type a number after stop" convenience isn't lost);
  `full`/`result`/`none` call `_finalize_and_quit(mode)`; `cancel` reverts
  to `awaiting_extend = True`. `_finalize_and_quit`:
  - `full` (default) - `_write_transcript()` one last time, extract final-
    answer code if any, then exit. Everything kept.
  - `result` - writes one distilled `_build_result_text()` to
    `<stem>_result.md`, then `unlink(missing_ok=True)`s the verbose
    transcript and reasoning log.
  - `none` - deletes the transcript, reasoning log, and `shutil.rmtree`s
    `code_dir` if it exists. Only ever touches this session's own
    `transcript_path`/`reasoning_path`/`code_dir` - never anything else.
  - All three (plus `ctrl+q`'s `action_quit_app`, the unconditional "quit
    now, keep everything" escape hatch, unaffected by any of this) funnel
    into a shared `_exit_now()` for the actual exit mechanics (the
    daemon safety-net timer). Deliberately NOT calling `action_quit_app()`
    from `_finalize_and_quit()` - it unconditionally re-extracts final-
    answer code, which would silently undo `none`'s deletion.
- Transcript is written continuously (not just at the end) to
  `~/Transcripts/disput_<session>.md`, each turn's reasoning wrapped in a
  collapsible `<details><summary>🧠 Thinking</summary>` block. Session IDs
  use microsecond precision (`%Y%m%d_%H%M%S_%f`) - second precision let two
  `DialogueScreen`s created within the same second (e.g. `ctrl+n` right
  after startup) collide and silently overwrite each other's transcript.

## Known open items

- Tool-call response parsing (see above) is unverified in practice.
- The Textual thread-worker turn loop assumes a real terminal; no
  non-interactive/headless mode exists (nor is one needed for this use case).

## Textual gotchas hit in this codebase (worth knowing before touching layout)

- **`Vertical` and `TextArea` both default to `height: 1fr`** - fill a
  fraction of the *viewport*, not size to content. Cost real debugging time
  twice: the setup wizard's Continue button was permanently pushed off
  Screen (TextArea eating all available space), and separately every
  turn's `.turn` wrapper was competing for a shrinking slice of `#log` as
  more turns got mounted - confirmed an early turn's region had literally
  collapsed to `height=0` with 7 turns present. Both fixed with an explicit
  `height: auto` / bounded `height:` override. Any new container or
  TextArea added to a screen needs one of these checked, not assumed.
- **Any non-scrollable Static fed user/model-controlled text needs a length
  cap - or make it genuinely scrollable instead.** The topic banner sits
  above `#log` as a plain `Static` and isn't scrollable itself - a huge
  pasted topic once grew it to 154 rows in a 24-row terminal, crushing the
  entire conversation down to 2 visible rows. It truncates the *display*
  (full text still goes to the model/transcript) plus carries a CSS
  `max-height` + `overflow-y: hidden` backstop. The Current Answer panel
  hit the same failure mode twice from two different angles - see the entry
  above - and was fixed differently: made it an actually-scrollable
  `VerticalScroll` (ctrl+f to expand) instead of truncating, since unlike
  the topic banner its content is something the user actively wants to
  read in full, not just skim. `#status` hit the inverse of this bug: fixed
  `height: 1` instead of `auto`, so a long status message (several run past
  140 chars) got silently clipped to one line instead of wrapping - same
  root lesson (don't fix the height of something whose content length you
  don't control), opposite direction (too short, not too tall).
- **`CollapsibleTitle` defaults to `width: auto`** - only as wide as its
  label text, left-anchored, while the bar rendered on screen spans the
  full container width. Clicking anywhere past the label silently did
  nothing. Fixed globally via `Collapsible > CollapsibleTitle { width: 1fr; }`.
- **Textual's command palette claims `ctrl+p` by default as a `priority=True`
  binding**, which unconditionally beats any screen-level binding on the
  same key - `ctrl+p` (Pause/Resume) silently never worked until
  `ENABLE_COMMAND_PALETTE = False` was set on `DisputApp`. Any future
  keybinding should be checked against `Input`/`TextArea`'s own claimed keys
  too (e.g. `ctrl+x` is "cut" on `Input` - `ctrl+g` was used for abort
  instead, specifically because it's unclaimed).

## Notable non-technical context

Gemma has an unprompted "Top Gun" persona easter egg - saying "talk to me,
Goose" flips it into a full Maverick/Goose call-and-response bit that
persists across unrelated follow-up questions (tested: it stayed in
character even answering a real weather query). Fun to show off in demos
alongside the actual dual-model debate mechanic.
