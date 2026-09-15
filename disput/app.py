"""Disput's TUI: setup wizard (pick/add a source, discover its models,
pick one, set a label + system prompt - twice, once per side) followed by
a live dialogue screen."""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from dataclasses import replace as replace_dataclass
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Collapsible,
    Footer,
    Header,
    Input,
    LoadingIndicator,
    Markdown,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from . import config as cfgstore
from .client import ModelConfig, ModelReply, call_model, list_models, make_client, save_final_answer_code

DEFAULT_TOPIC = (
    "Collaborate and design a simple terminal application that shows a more "
    "human-readable version of `top`. Work together: propose an approach, "
    "critique each other's ideas, and converge on a concrete plan (language, "
    "what data to show, how to format it) before either of you writes code."
)

DEFAULT_SYSTEM_TEMPLATE = (
    "You are {label}, one of two AI models in a live two-way dialogue with {other_label}. "
    "Engage critically and specifically - if something the other model says seems wrong, "
    "unsupported, or overconfident, say so rather than deferring just because it is bigger "
    "or was here first. Keep responses focused and under 200 words unless you're writing code."
)

# Fixed, not CWD-relative: a pipx/pip install -e . install puts `disput` on
# PATH globally, so it's runnable from any directory - a relative path here
# meant output scattered wherever the user happened to be standing when
# they launched it, with no predictable place to find it afterward.
TRANSCRIPTS_DIR = Path.home() / "Transcripts"
OUTPUT_DIR = TRANSCRIPTS_DIR / "dialogue_output"
DEFAULT_ROUNDS = 6


def guess_label(model_id: str) -> str:
    """Turns a model id like 'Blackfrost-AI/Qwen3.8-27B-ABLITERATED-GGUF'
    into a short display label like 'Qwen3.8-27B-ABLITERATED'."""
    tail = model_id.split("/")[-1]
    tail = re.sub(r"-GGUF$", "", tail, flags=re.IGNORECASE)
    return tail or model_id


# ============================== Setup wizard ================================


class SourceSetupScreen(Screen):
    """One full pass of: pick-or-add a source -> fetch its models -> pick a
    model -> set label + system prompt. Dismisses with a ModelConfig."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("e", "edit_highlighted_source", "Edit source"),
        ("d", "delete_highlighted_source", "Delete source"),
        ("ctrl+s", "submit_details", "Continue"),
    ]

    def __init__(self, side_label: str, other_label: str) -> None:
        super().__init__()
        self.side_label = side_label
        self.other_label = other_label
        self.chosen_source: cfgstore.Source | None = None
        self.chosen_model: str | None = None
        self._sources: list[cfgstore.Source] = []
        self._editing_source: cfgstore.Source | None = None
        self._delete_candidate: cfgstore.Source | None = None
        self._last_models: list[str] = []
        # Tracks which internal wizard step is showing, so `escape` can step
        # back through them instead of popping the whole screen - popping
        # here would reveal the app's empty base screen (a previous step's
        # screen is already gone by the time this one exists), not a real
        # "back" destination, which is what caused the black-screen bug.
        self._step = "source"

    def compose(self) -> ComposeResult:
        yield Header()
        title = Static(f" Setting up Model {self.side_label} ", id="step-title")
        title.tooltip = self._role_hint_text()  # free - costs no vertical space
        yield title
        yield VerticalScroll(id="body")
        yield Footer()

    def _role_hint_text(self) -> str:
        # The turn order is fixed (A always goes first, B always second),
        # which quietly assigns asymmetric roles for any topic that asks
        # for one ("one of you propose, the other critique") - worth
        # surfacing up front rather than users discovering it by asking.
        if self.side_label == "A":
            return (
                "Model A goes first every turn - it sees the bare topic with no other "
                "input yet, so it effectively becomes the proposer for any topic that "
                "assigns asymmetric roles."
            )
        return (
            "Model B always responds second, after seeing Model A's turn - it "
            "effectively becomes the chaperone/critic: reacting to and checking A's "
            "output rather than opening cold."
        )

    def on_mount(self) -> None:
        self.show_source_step()

    def set_body(self, *widgets) -> None:
        body = self.query_one("#body", VerticalScroll)
        body.remove_children()
        body.mount_all(widgets)

    # -- step 1: pick or add a source -----------------------------------

    def show_source_step(self) -> None:
        self._step = "source"
        self._sources = cfgstore.load_sources()
        options = [
            Option(f"{s.name}  —  {s.base_url}", id=f"src-{i}") for i, s in enumerate(self._sources)
        ]
        options.append(Option("+ Add a new source (endpoint + API key)", id="__new__"))
        self.set_body(
            Static(f"[dim]{self._role_hint_text()}[/dim]"),
            Static("Pick a saved source, or add a new one:"),
            OptionList(*options, id="source-list"),
            Static("[dim]Enter: use it   •   e: edit   •   d: delete the highlighted source[/dim]"),
        )
        self.query_one("#source-list", OptionList).focus()

    def action_go_back(self) -> None:
        """Step back through the wizard's own steps. Deliberately never
        pops the Screen itself: by the time a later step exists, the screen
        for whatever came before it (e.g. Model A's setup) has usually
        already been dismissed, so popping would reveal the app's empty
        base screen instead of anything navigable."""
        if self._step == "source":
            return  # nothing earlier to go back to within this screen
        if self._step in ("custom_source", "fetch_error", "model", "manual_model", "confirm_delete"):
            self.show_source_step()
        elif self._step == "details":
            if self._last_models:
                self.show_model_step(self._last_models)
            else:
                self.show_manual_model_step()

    def action_edit_highlighted_source(self) -> None:
        try:
            option_list = self.query_one("#source-list", OptionList)
        except Exception:
            return
        idx = option_list.highlighted
        if idx is None or idx >= len(self._sources):
            return
        self.show_custom_source_step(editing=self._sources[idx])

    def action_delete_highlighted_source(self) -> None:
        try:
            option_list = self.query_one("#source-list", OptionList)
        except Exception:
            return
        idx = option_list.highlighted
        if idx is None or idx >= len(self._sources):
            return
        self.show_confirm_delete_step(self._sources[idx])

    def show_confirm_delete_step(self, source: cfgstore.Source) -> None:
        self._step = "confirm_delete"
        self._delete_candidate = source
        self.set_body(
            Static(f"Delete saved source '{source.name}' ({source.base_url})?"),
            Static("[dim]This only removes it from Disput's saved list - nothing happens to the server itself.[/dim]"),
            Horizontal(
                Button("Delete", id="confirm-delete-btn", variant="error"),
                Button("Cancel", id="cancel-delete-btn"),
            ),
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        list_id = event.option_list.id
        opt_id = event.option.id or ""
        if list_id == "source-list":
            if opt_id == "__new__":
                self.show_custom_source_step()
            else:
                index = int(opt_id.split("-")[1])
                self.chosen_source = self._sources[index]
                self.fetch_models()
        elif list_id == "model-list":
            if opt_id == "__manual__":
                self.show_manual_model_step()
            else:
                self.chosen_model = opt_id
                self.show_details_step()

    # -- step 1b: add a new source ---------------------------------------

    def show_custom_source_step(self, editing: cfgstore.Source | None = None) -> None:
        self._step = "custom_source"
        self._editing_source = editing
        title = f"Editing '{editing.name}' (change the name to save as a new source instead):" if editing else "New source:"
        self.set_body(
            Static(title),
            Input(value=editing.name if editing else "", placeholder="Name (e.g. Local Mac / Unsloth)", id="src-name"),
            Input(value=editing.base_url if editing else "", placeholder="Base URL (e.g. http://localhost:8888/v1)", id="src-url"),
            Input(value=editing.api_key if editing else "", placeholder="API key", password=True, id="src-key"),
            Input(
                value=",".join(editing.enabled_tools) if editing else "",
                placeholder="Server-side tools, comma-separated (optional, e.g. python,terminal)",
                id="src-tools",
            ),
            Button("Save & Continue", id="save-source-btn", variant="primary"),
        )
        self.query_one("#src-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-source-btn":
            self.save_custom_source()
        elif event.button.id == "manual-model-btn":
            self.show_manual_model_step()
        elif event.button.id == "retry-fetch-btn":
            self.fetch_models()
        elif event.button.id == "back-to-source-btn":
            self.show_source_step()
        elif event.button.id == "manual-model-continue-btn":
            self.confirm_manual_model()
        elif event.button.id == "details-continue-btn":
            self.finish_details()
        elif event.button.id == "confirm-delete-btn":
            if self._delete_candidate:
                cfgstore.delete_source(self._delete_candidate.name)
                self._delete_candidate = None
            self.show_source_step()
        elif event.button.id == "cancel-delete-btn":
            self._delete_candidate = None
            self.show_source_step()

    def save_custom_source(self) -> None:
        name = self.query_one("#src-name", Input).value.strip()
        url = self.query_one("#src-url", Input).value.strip()
        key = self.query_one("#src-key", Input).value.strip()
        tools_raw = self.query_one("#src-tools", Input).value.strip()
        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        editing = self._editing_source
        if not name or not url:
            self.set_body(Static("[red]Name and base URL are both required.[/red]"))
            self.set_timer(1.5, lambda: self.show_custom_source_step(editing))
            return
        source = cfgstore.Source(name=name, base_url=url, api_key=key, enabled_tools=tools)
        cfgstore.upsert_source(source, old_name=editing.name if editing else None)
        self.chosen_source = source
        self.fetch_models()

    # -- step 2: fetch models from the chosen source ----------------------

    def fetch_models(self) -> None:
        self._step = "fetching"
        self.set_body(
            LoadingIndicator(),
            Static(f"Fetching models from {self.chosen_source.base_url} ..."),
        )
        self._do_fetch_models()

    @work(thread=True)
    def _do_fetch_models(self) -> None:
        source = self.chosen_source
        try:
            models = list_models(source.base_url, source.api_key)
        except Exception as exc:  # noqa: BLE001 - surfacing any backend/network error to the user
            self.app.call_from_thread(self.show_fetch_error, exc)
            return
        self.app.call_from_thread(self.show_model_step, models)

    def show_fetch_error(self, exc: Exception) -> None:
        self._step = "fetch_error"
        self.set_body(
            Static(f"[red]Couldn't fetch models: {exc}[/red]"),
            Horizontal(
                Button("Retry", id="retry-fetch-btn"),
                Button("Enter model id manually", id="manual-model-btn"),
                Button("Back", id="back-to-source-btn"),
            ),
        )

    def show_model_step(self, models: list[str]) -> None:
        if not models:
            self.show_fetch_error(RuntimeError("source reported zero models"))
            return
        self._step = "model"
        self._last_models = models
        options = [Option(m, id=m) for m in models]
        options.append(Option("(enter a model id manually instead)", id="__manual__"))
        self.set_body(
            Static(f"Models available at {self.chosen_source.base_url}:"),
            OptionList(*options, id="model-list"),
        )
        self.query_one("#model-list", OptionList).focus()

    def show_manual_model_step(self) -> None:
        self._step = "manual_model"
        self.set_body(
            Static("Enter the exact model id as the server expects it:"),
            Input(placeholder="e.g. unsloth/gemma-4-26B-A4B-it-GGUF", id="manual-model-input"),
            Button("Continue", id="manual-model-continue-btn"),
        )
        self.query_one("#manual-model-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in ("src-name", "src-url", "src-key", "src-tools"):
            self.save_custom_source()
        elif event.input.id == "manual-model-input":
            self.confirm_manual_model()
        elif event.input.id == "label-input":
            self.finish_details()

    def confirm_manual_model(self) -> None:
        value = self.query_one("#manual-model-input", Input).value.strip()
        if value:
            self.chosen_model = value
            self.show_details_step()

    # -- step 3: label + system prompt ------------------------------------

    def show_details_step(self) -> None:
        self._step = "details"
        label = guess_label(self.chosen_model)
        prompt = DEFAULT_SYSTEM_TEMPLATE.format(label=label, other_label=self.other_label)
        self.set_body(
            Static(f"Model: [b]{self.chosen_model}[/b]"),
            Static("Display label:"),
            Input(value=label, id="label-input"),
            Static("System prompt:"),
            TextArea(prompt, id="prompt-area"),
            Button("Continue", id="details-continue-btn", variant="primary"),
            Static("[dim]ctrl+s: continue (works even while editing the system prompt)[/dim]"),
        )
        self.query_one("#label-input", Input).focus()

    def action_submit_details(self) -> None:
        # Guarded because this binding is screen-wide but only valid on the
        # details step - harmless no-op on every other step.
        if self.query("#details-continue-btn"):
            self.finish_details()

    def finish_details(self) -> None:
        label = self.query_one("#label-input", Input).value.strip() or self.chosen_model
        prompt = self.query_one("#prompt-area", TextArea).text.strip()
        cfg = ModelConfig(
            label=label,
            base_url=self.chosen_source.base_url,
            api_key=self.chosen_source.api_key,
            model=self.chosen_model,
            system_prompt=prompt,
            enabled_tools=list(self.chosen_source.enabled_tools),
        )
        self.dismiss(cfg)


class TopicScreen(Screen):
    """Set the starting topic/prompt and how many turns to run."""

    BINDINGS = [("ctrl+s", "submit_topic", "Start dialogue")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" Topic & length ", id="step-title")
        yield VerticalScroll(
            Static("Starting topic/prompt for the dialogue:"),
            Static(f"[dim]e.g. {DEFAULT_TOPIC}[/dim]"),
            TextArea("", id="topic-area"),
            Static("How many turns total?"),
            Input(value=str(DEFAULT_ROUNDS), id="rounds-input"),
            Button("Start Dialogue", id="start-btn", variant="primary"),
            Static("[dim]ctrl+s: start (works even while editing the topic)[/dim]"),
            id="body",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.start_dialogue()

    def action_submit_topic(self) -> None:
        self.start_dialogue()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "rounds-input":
            self.start_dialogue()

    def start_dialogue(self) -> None:
        topic_area = self.query_one("#topic-area", TextArea)
        topic = topic_area.text.strip()
        if not topic:
            topic_area.focus()
            self.notify("Type a starting topic before continuing.", severity="warning")
            return
        rounds_raw = self.query_one("#rounds-input", Input).value.strip()
        rounds = int(rounds_raw) if rounds_raw.isdigit() and int(rounds_raw) > 0 else DEFAULT_ROUNDS
        self.dismiss((topic, rounds))


# ============================== Live dialogue ================================


class DialogueScreen(Screen):
    BINDINGS = [
        ("ctrl+p", "toggle_pause", "Pause/Resume"),
        ("ctrl+q", "quit_app", "Quit & Save"),
        ("ctrl+g", "abort_turn", "Abort turn"),
        ("ctrl+n", "new_topic", "New topic (same models)"),
        ("ctrl+f", "toggle_answer_panel", "Expand/collapse answer"),
        ("escape", "fix_broken_model", "Fix model (after an error)"),
    ]

    ANSWER_PANEL_COMPACT_HEIGHT = 8
    ANSWER_PANEL_EXPANDED_HEIGHT = 20

    def __init__(self, cfg_a: ModelConfig, cfg_b: ModelConfig, topic: str, total_rounds: int) -> None:
        super().__init__()
        self.cfg_a = cfg_a
        self.cfg_b = cfg_b
        self.topic = topic
        self.total_rounds = total_rounds

        self.client_a = make_client(cfg_a.base_url, cfg_a.api_key)
        self.client_b = make_client(cfg_b.base_url, cfg_b.api_key)

        self.history_a: list[dict] = [{"role": "user", "content": topic}]
        self.history_b: list[dict] = [{"role": "user", "content": topic}]

        self.turn = 0
        self.current = "A"
        self.paused = False
        self.awaiting_extend = False
        self.turn_in_progress = False
        self._error_side: str | None = None
        self._abort_requested = False
        self._latest_answer: str | None = None
        self._latest_answer_meta: tuple[int, str] | None = None  # (turn_no, label)
        # Both sides must independently signal [DONE] before it's treated as
        # real agreement to stop early - reset for whichever side speaks
        # without the signal, so it always reflects each side's MOST RECENT
        # turn, not some stale agreement from many turns ago.
        self._converged = {"A": False, "B": False}
        self._usage_tokens = {"A": 0, "B": 0}  # cumulative total_tokens per side
        self._answer_expanded = False
        self._final_answer_mounted_for: int | None = None  # turn_no already appended to the log
        self._awaiting_save_choice = False
        self._current_client: OpenAI | None = None
        self._turn_started_at: float | None = None

        # Microsecond precision, not just seconds: two DialogueScreens can
        # genuinely be constructed within the same second (e.g. ctrl+n
        # starting a new topic right after the previous one), and a
        # collision here means the new session silently overwrites the
        # old one's transcript file rather than getting its own.
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        self.transcript_path = TRANSCRIPTS_DIR / f"disput_{session_id}.md"
        self.reasoning_path = TRANSCRIPTS_DIR / f"disput_{session_id}_reasoning.log"
        self.code_dir = OUTPUT_DIR / session_id

        self.transcript_lines = [
            f"# Disput Session\n",
            f"**Topic:** {topic}\n",
            f"**Model A:** {cfg_a.label} ({cfg_a.model})\n",
            f"**Model B:** {cfg_b.label} ({cfg_b.model})\n",
            f"**Started:** {datetime.now().isoformat()}\n",
        ]
        self._write_transcript()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"[b]Topic:[/b] {self._topic_banner_text()}", id="topic-banner")
        yield VerticalScroll(
            Static(self._answer_panel_text(), id="answer-panel-text"),
            id="answer-panel",
        )
        yield VerticalScroll(id="log")
        yield Static("", id="status")
        yield Input(placeholder="Type a moderator note and press Enter (or just watch it run)...", id="moderator-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#moderator-input", Input).focus()
        self.set_interval(1.0, self._tick_thinking_status)
        self._update_usage_title()
        self._apply_answer_panel_height()
        self.take_turn()

    def action_toggle_answer_panel(self) -> None:
        self._answer_expanded = not self._answer_expanded
        self._apply_answer_panel_height()

    def _apply_answer_panel_height(self) -> None:
        # Before there's an actual answer, the panel holds one placeholder
        # line - reserving a full compact/expanded height for that (rather
        # than sizing to content) was exactly the bug that crushed the log
        # with a huge topic: two fixed-height elements above #log, one of
        # them empty, eating rows for nothing. Only claim real space once
        # there's something worth showing.
        panel = self.query_one("#answer-panel")
        if self._latest_answer is None:
            panel.styles.height = "auto"
        elif self._answer_expanded:
            panel.styles.height = self.ANSWER_PANEL_EXPANDED_HEIGHT
        else:
            panel.styles.height = self.ANSWER_PANEL_COMPACT_HEIGHT

    # -- turn loop ---------------------------------------------------------

    @work(thread=True, exclusive=True, group="turn")
    def take_turn(self) -> None:
        if self.paused or self.awaiting_extend or self.turn_in_progress:
            return
        self.turn_in_progress = True
        turn_no = self.turn + 1
        current = self.current
        cfg = self.cfg_a if current == "A" else self.cfg_b
        client = self.client_a if current == "A" else self.client_b
        history = list(self.history_a if current == "A" else self.history_b)

        self._current_client = client
        self.app.call_from_thread(self._begin_turn_status, turn_no, cfg.label)
        try:
            # Neither model otherwise has any sense of how much runway is
            # left, which tends to produce aimless back-and-forth ("ping
            # pong") instead of working toward a conclusion - silently
            # folded into the system prompt for this call only (never shown
            # in the transcript/log, and doesn't touch the real cfg_a/cfg_b
            # or conversation history) so it stays accurate even if the
            # dialogue gets extended later.
            turns_remaining = self.total_rounds - turn_no + 1
            budget_note = (
                f"\n\n[Dialogue budget: this is turn {turn_no} of {self.total_rounds} total turns "
                f"({turns_remaining} remaining, including this one). Pace yourself - if turns are "
                f"running low, work toward a concrete conclusion instead of continuing to go back "
                f"and forth.]"
            )
            # Same silent-injection trick: once there's a concrete answer,
            # get it out of the back-and-forth and into something the user
            # can see without reading N turns of the two of you agreeing
            # with each other.
            answer_note = (
                "\n\n[If you and the other model have arrived at a concrete answer, wrap it in "
                "<answer>...</answer> tags so it can be shown clearly - you can keep discussing "
                "afterward, and post a new <answer> block later if you refine it. Don't repeat an "
                "unchanged answer block turn after turn once nothing new has been added.]"
            )
            # A third silent note: once BOTH of you have nothing left to
            # add, keep saying so forever is exactly the "ping pong
            # self-congratulation" this exists to cut short. Only acted on
            # if both sides signal it (see handle_turn_result) - one model
            # alone declaring victory isn't enough to actually stop early.
            done_note = (
                "\n\n[If you genuinely have nothing more to add - the discussion has reached a "
                "real conclusion, not just agreement for its own sake - end your reply with the "
                "exact token [DONE] on its own line. Only do this if there's truly nothing left; "
                "if the other model raises something new, engage with it instead.]"
            )
            call_cfg = replace_dataclass(
                cfg, system_prompt=cfg.system_prompt + budget_note + answer_note + done_note
            )
            reply = call_model(client, call_cfg, history)
        except Exception as exc:  # noqa: BLE001 - network/backend error, surface and pause rather than crash
            if self._abort_requested:
                self._abort_requested = False
                self.app.call_from_thread(self.handle_turn_aborted, current)
            else:
                self.app.call_from_thread(self.handle_turn_error, current, cfg, exc)
            return
        self.app.call_from_thread(self.handle_turn_result, turn_no, current, cfg, reply)

    def _begin_turn_status(self, turn_no: int, label: str) -> None:
        self._turn_started_at = time.monotonic()
        self.set_status(f"Turn {turn_no}: {label} thinking… (ctrl+g to abort)")

    def _tick_thinking_status(self) -> None:
        # Runs every second regardless of state; only actually does
        # anything while a call is genuinely in flight. The point is purely
        # to prove the app is alive - a real model call can legitimately
        # take minutes, and a status line that never changes is
        # indistinguishable from one that's actually stuck.
        if not self.turn_in_progress or self._turn_started_at is None:
            return
        elapsed = int(time.monotonic() - self._turn_started_at)
        current = self.current
        label = self.cfg_a.label if current == "A" else self.cfg_b.label
        turn_no = self.turn + 1
        self.set_status(f"Turn {turn_no}: {label} thinking… {elapsed}s (ctrl+g to abort)")

    def action_abort_turn(self) -> None:
        if not self.turn_in_progress:
            return  # nothing in flight to abort
        self._abort_requested = True
        # Best-effort: closing the client's connection pool out from under
        # an in-flight request is enough to make most local servers raise a
        # transport error and give up, which is the only real cancellation
        # lever the sync openai client offers.
        if self._current_client is not None:
            try:
                self._current_client.close()
            except Exception:
                pass

    def handle_turn_aborted(self, current: str) -> None:
        self.turn_in_progress = False
        self.paused = True
        # The old client's connection pool was just torn down to abort the
        # request - replace it so the next attempt gets a working one.
        if current == "A":
            self.client_a = make_client(self.cfg_a.base_url, self.cfg_a.api_key)
        else:
            self.client_b = make_client(self.cfg_b.base_url, self.cfg_b.api_key)
        self.mount_note("[yellow]Turn aborted.[/yellow]")
        self.set_status(
            f"Turn aborted. Type a moderator note to redirect Model {current} if you like, then ctrl+p to continue."
        )

    def handle_turn_error(self, current: str, cfg: ModelConfig, exc: Exception) -> None:
        self.turn_in_progress = False
        self.paused = True
        self._error_side = current
        self.mount_note(f"[red]Error calling model: {exc}[/red]")
        self.set_status(
            f"Paused after an error. ctrl+p to retry as-is, or escape to swap out Model {current}'s "
            f"source/model ({cfg.label})."
        )

    def action_fix_broken_model(self) -> None:
        if self._error_side is None:
            return  # nothing broken right now - don't let escape do anything surprising
        side = self._error_side
        other_label = self.cfg_b.label if side == "A" else self.cfg_a.label
        self.app.push_screen(
            SourceSetupScreen(side_label=side, other_label=other_label),
            callback=self._model_fixed,
        )

    def _model_fixed(self, new_cfg: ModelConfig) -> None:
        side = self._error_side
        if side == "A":
            self.cfg_a = new_cfg
            self.client_a = make_client(new_cfg.base_url, new_cfg.api_key)
        else:
            self.cfg_b = new_cfg
            self.client_b = make_client(new_cfg.base_url, new_cfg.api_key)
        self.mount_note(f"Model {side} switched to {new_cfg.label} ({new_cfg.model}). Resuming...")
        self._error_side = None
        self.paused = False
        self.set_status("")
        self.take_turn()

    def handle_turn_result(self, turn_no: int, current: str, cfg: ModelConfig, reply: ModelReply) -> None:
        self.turn = turn_no
        other = "B" if current == "A" else "A"

        self._usage_tokens[current] += reply.total_tokens
        self._update_usage_title()

        self.mount_turn_widget(turn_no, current, cfg, reply)

        self.history_a.append({"role": "assistant" if current == "A" else "user", "content": reply.final})
        self.history_b.append({"role": "assistant" if current == "B" else "user", "content": reply.final})

        if reply.answer:
            self._latest_answer = reply.answer
            self._latest_answer_meta = (turn_no, cfg.label)
            self.query_one("#answer-panel-text", Static).update(self._answer_panel_text())
            self._apply_answer_panel_height()
            self.transcript_lines.append(
                f"**✅ Current answer (as of Turn {turn_no} — {cfg.label}):**\n\n{reply.answer}\n"
            )

        self._append_transcript_turn(turn_no, cfg, reply)
        if reply.thinking:
            self._append_reasoning(turn_no, cfg.label, reply.thinking)

        self.current = other
        self.turn_in_progress = False
        self._converged[current] = reply.done

        if self.turn >= self.total_rounds:
            self.awaiting_extend = True
            self._mount_final_answer_block()
            self.set_status(
                f"Reached {self.total_rounds} turns. Type a number to extend, or 'stop' to finish "
                f"(ctrl+q quits and saves; a plain note here is just logged, not treated as 'stop')."
            )
            return

        if self._converged["A"] and self._converged["B"]:
            self._converged["A"] = False
            self._converged["B"] = False
            self.awaiting_extend = True
            self.mount_note("[green]Both models signaled they have nothing more to add.[/green]")
            self._mount_final_answer_block()
            self.set_status(
                f"Both models signaled agreement at turn {self.turn} (of your planned "
                f"{self.total_rounds}). Type a number to add more turns, 'stop' to finish now, or "
                f"anything else to leave a note and keep going."
            )
            return

        self.set_status("")
        if not self.paused:
            self.set_timer(0.5, self.take_turn)

    # -- moderator / extend input -------------------------------------------

    STOP_WORDS = {"stop", "no", "n", "q", "quit", "done", "end"}
    SAVE_CHOICE_PROMPT = (
        "How should this be saved? 'full' (transcript + reasoning log - default), "
        "'result' (just the topic + final answer), or 'none' (discard everything from this "
        "run) - or 'cancel' to keep going instead."
    )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "moderator-input":
            return
        value = event.value.strip()
        event.input.value = ""

        if self._awaiting_save_choice:
            self._handle_save_choice(value)
            return

        if self.awaiting_extend:
            if value.isdigit() and int(value) > 0:
                self.total_rounds += int(value)
                self.awaiting_extend = False
                self.mount_note(f"Extending — now running to turn {self.total_rounds}.")
                self.set_status("")
                self.take_turn()
            elif not value or value.lower() in self.STOP_WORDS:
                # Doesn't quit outright from this text box - moves into an
                # explicit save-mode choice instead, which can itself be
                # cancelled to come back here. ctrl+q remains the
                # unconditional "just quit and keep everything, right now"
                # escape hatch, unaffected by any of this.
                self.awaiting_extend = False
                self._awaiting_save_choice = True
                self.mount_note(f"[yellow]Stopped at {self.total_rounds} turns.[/yellow]")
                self.set_status(self.SAVE_CHOICE_PROMPT)
            else:
                # Not a number and not a recognized "stop" word - treat it as
                # a genuine moderator note rather than guessing, and keep
                # waiting for an actual extend/stop decision.
                self._inject_moderator_note(value)
                self.set_status(
                    f"Reached {self.total_rounds} turns. Type a number to extend, or 'stop' to finish."
                )
            return

        if value:
            self._inject_moderator_note(value)

    def _handle_save_choice(self, value: str) -> None:
        choice = value.strip().lower()
        if choice.isdigit() and int(choice) > 0:
            # Typing a number always means "give me more turns," regardless
            # of which sub-prompt is showing - equivalent to 'cancel' then
            # extending, in one step, rather than forcing that as two.
            self._awaiting_save_choice = False
            self.total_rounds += int(choice)
            self.awaiting_extend = False
            self.mount_note(f"Extending — now running to turn {self.total_rounds}.")
            self.set_status("")
            self.take_turn()
        elif choice in ("", "full", "f"):
            self._finalize_and_quit("full")
        elif choice in ("result", "r", "end", "e"):
            self._finalize_and_quit("result")
        elif choice in ("none", "n", "discard"):
            self._finalize_and_quit("none")
        elif choice in ("cancel", "c", "back", "resume"):
            self._awaiting_save_choice = False
            self.awaiting_extend = True
            self.mount_note("Cancelled - back to where you left off.")
            self.set_status(
                f"Stopped at {self.total_rounds} turns. Type a number to extend, or 'stop' to finish "
                f"(ctrl+q quits and saves)."
            )
        else:
            self.mount_note(f"[red]Didn't understand '{value}'.[/red]")
            self.set_status(self.SAVE_CHOICE_PROMPT)

    def _finalize_and_quit(self, mode: str) -> None:
        """mode is 'full' (keep everything, default), 'result' (replace the
        verbose transcript/reasoning log with one distilled result file), or
        'none' (discard every file this session produced). Only ever
        touches this session's own transcript_path/reasoning_path/code_dir -
        never anything else."""
        if mode in ("full", "result") and self._latest_answer:
            save_final_answer_code(self._latest_answer, self.code_dir)

        if mode == "full":
            self._write_transcript()
        elif mode == "result":
            result_path = self.transcript_path.with_name(self.transcript_path.stem + "_result.md")
            result_path.write_text(self._build_result_text())
            self.transcript_path.unlink(missing_ok=True)
            self.reasoning_path.unlink(missing_ok=True)
        elif mode == "none":
            self.transcript_path.unlink(missing_ok=True)
            self.reasoning_path.unlink(missing_ok=True)
            if self.code_dir.exists():
                shutil.rmtree(self.code_dir, ignore_errors=True)

        self._exit_now()

    def _build_result_text(self) -> str:
        lines = [
            "# Disput Result\n",
            f"**Topic:** {self.topic}\n",
            f"**Model A:** {self.cfg_a.label} ({self.cfg_a.model})\n",
            f"**Model B:** {self.cfg_b.label} ({self.cfg_b.model})\n",
            f"**Turns:** {self.turn}\n",
        ]
        if self._latest_answer:
            turn_no, label = self._latest_answer_meta
            lines.append(f"\n## Final Answer\n\n_(reached on Turn {turn_no} — {label})_\n\n{self._latest_answer}\n")
        else:
            lines.append("\n_No <answer> block was ever produced during this run._\n")
        return "\n".join(lines)

    def _inject_moderator_note(self, value: str) -> None:
        injected = f"[Moderator note]: {value}"
        self.history_a.append({"role": "user", "content": injected})
        self.history_b.append({"role": "user", "content": injected})
        self.mount_note(f"🗣  Moderator: {value}")
        self.transcript_lines.append(f"### Moderator (after turn {self.turn})\n\n{value}\n")
        self._write_transcript()

    # -- actions -------------------------------------------------------------

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self.set_status("Paused. Press ctrl+p to resume.")
        else:
            self.set_status("")
            if not self.turn_in_progress and not self.awaiting_extend:
                self.take_turn()

    def action_quit_app(self) -> None:
        # ctrl+q: unconditional "just quit and keep everything, right now"
        # escape hatch - always the 'full' behavior, unaffected by whatever
        # state the save-choice flow (_finalize_and_quit) is in.
        self._write_transcript()
        if self._latest_answer:
            save_final_answer_code(self._latest_answer, self.code_dir)
        self._exit_now()

    def _exit_now(self) -> None:
        self.app.exit()
        # Safety net: a still-blocked in-flight call_model() (e.g. a remote
        # model taking a long time) runs on a thread-pool worker thread, and
        # Python won't let the process actually terminate until every such
        # thread finishes - confirmed this can leave ctrl+q unable to
        # force-quit for as long as that call takes, with no cap. Give
        # Textual's own teardown (which restores the terminal - usually
        # near-instant) a couple of seconds to finish normally, then
        # guarantee the process actually ends regardless of what any
        # background thread is still doing. Never fires in the normal case:
        # the process has already fully exited well within 2s.
        force_exit_timer = threading.Timer(2.0, os._exit, args=(0,))
        force_exit_timer.daemon = True  # must not itself hold up a normal, fast exit
        force_exit_timer.start()

    def action_new_topic(self) -> None:
        if self.turn_in_progress:
            return  # abort the in-flight turn first (ctrl+g), then retry
        self.app.push_screen(TopicScreen(), callback=self._start_new_topic)

    def _start_new_topic(self, result: tuple[str, int]) -> None:
        topic, rounds = result
        # Same models/sources (cfg_a/cfg_b carried over as-is), but
        # everything else - history, turn count, transcript/reasoning/code
        # output files - starts completely fresh via a brand new screen
        # rather than trying to reset this one in place.
        new_screen = DialogueScreen(self.cfg_a, self.cfg_b, topic, rounds)
        self.app.pop_screen()
        self.app.push_screen(new_screen)

    # -- UI helpers ------------------------------------------------------------

    TOPIC_BANNER_PREVIEW_CHARS = 240

    def _topic_banner_text(self) -> str:
        # The banner isn't scrollable and sits above the log, so with no
        # cap here a long pasted topic would grow to fill the whole screen
        # and crush the actual conversation down to nothing (confirmed:
        # a ~11k-char paste left only 2 rows visible for the entire log in
        # a 24-row terminal). The full topic still goes to both models
        # unchanged - this only shortens what's DISPLAYED.
        topic = self.topic
        if len(topic) <= self.TOPIC_BANNER_PREVIEW_CHARS:
            return topic
        return (
            topic[: self.TOPIC_BANNER_PREVIEW_CHARS].rstrip()
            + f"… [{len(topic)} chars total - shown truncated, sent to both models in full]"
        )

    def _answer_panel_text(self) -> str:
        if self._latest_answer is None:
            return "[dim]No answer proposed yet.[/dim]"
        turn_no, label = self._latest_answer_meta
        # Unlike the topic banner, this panel lives inside its own
        # VerticalScroll (id="answer-panel") - it can be scrolled
        # independently of the main log instead of needing truncation, so
        # the full answer is always shown here. ctrl+f expands it further
        # for a longer answer.
        return f"[b]✅ Current answer[/b] (as of Turn {turn_no} — {label}) - ctrl+f to expand/scroll:\n\n{self._latest_answer}"

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _update_usage_title(self) -> None:
        # Shows live in the title bar (Header renders Screen.sub_title next
        # to the app title) - cumulative total_tokens per model, real usage
        # data straight from each response's `usage` object, useful for
        # actually comparing what two disparate models/hardware cost to
        # reach whatever conclusion they reached.
        # Full model labels (can be long, e.g. "MiniCPM5-2B-heretic-
        # abliterated") left almost no room in the title bar - just the
        # side letter is enough context here since the labels are already
        # shown throughout the log itself.
        a_tokens = self._usage_tokens["A"]
        b_tokens = self._usage_tokens["B"]
        self.sub_title = f"A: {a_tokens:,} tok  ·  B: {b_tokens:,} tok"

    def mount_turn_widget(self, turn_no: int, current: str, cfg: ModelConfig, reply: ModelReply) -> None:
        log = self.query_one("#log", VerticalScroll)
        children = [Static(f"[b]Turn {turn_no} — {cfg.label}[/b]", classes=f"turn-header turn-{current.lower()}")]
        if reply.thinking:
            children.append(Collapsible(Static(reply.thinking), title="🧠 Thinking", collapsed=True))
        children.append(Markdown(reply.final or "*(empty reply)*"))
        log.mount(Vertical(*children, classes="turn"))
        log.scroll_end(animate=False)

    def mount_note(self, text: str) -> None:
        log = self.query_one("#log", VerticalScroll)
        log.mount(Static(text, classes="note"))
        log.scroll_end(animate=False)

    def _mount_final_answer_block(self) -> None:
        """Appends the current answer directly into the scrollable dialogue
        log as its own clearly-marked block, once, whenever the run pauses
        (turn limit or mutual convergence) - so it's readable in full as
        part of the normal scrollback rather than only in the small
        (though independently scrollable) answer panel above the log."""
        if self._latest_answer is None:
            return
        turn_no, label = self._latest_answer_meta
        if self._final_answer_mounted_for == turn_no:
            return  # already appended this exact answer - don't duplicate on a re-trigger
        self._final_answer_mounted_for = turn_no
        log = self.query_one("#log", VerticalScroll)
        log.mount(
            Vertical(
                Static(f"[b]🏁 Final Answer[/b] (from Turn {turn_no} — {label}):", classes="final-answer-header"),
                Markdown(self._latest_answer),
                classes="turn final-answer",
            )
        )
        log.scroll_end(animate=False)

    # -- persistence -----------------------------------------------------------

    def _append_transcript_turn(self, turn_no: int, cfg: ModelConfig, reply: ModelReply) -> None:
        if reply.thinking:
            self.transcript_lines.append(
                f"### Turn {turn_no} — {cfg.label}\n\n"
                f"<details><summary>🧠 Thinking</summary>\n\n{reply.thinking}\n\n</details>\n\n"
                f"{reply.final}\n"
            )
        else:
            self.transcript_lines.append(f"### Turn {turn_no} — {cfg.label}\n\n{reply.final}\n")
        self._write_transcript()

    def _write_transcript(self) -> None:
        self.transcript_path.write_text("\n".join(self.transcript_lines))

    def _append_reasoning(self, turn_no: int, label: str, thinking: str) -> None:
        with open(self.reasoning_path, "a") as f:
            f.write(f"\n{'=' * 60}\n[Turn {turn_no}] {label} thinking:\n{'-' * 60}\n{thinking}\n")


# ============================== App ================================


class DisputApp(App):
    TITLE = "Disput"
    # Textual's command palette defaults to ctrl+p as a *priority* binding,
    # which unconditionally wins over any screen-level binding for the same
    # key - silently swallowing DialogueScreen's ctrl+p (Pause/Resume) every
    # time. Disput has no command providers to offer the palette anyway, so
    # just disable it and reclaim the key.
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #step-title { padding: 1 2; text-style: bold; }
    #role-hint { padding: 0 2 1 2; }
    #body { padding: 1 2; height: auto; }
    /* TextArea defaults to height: 1fr (greedily fills all remaining space
       in its container), which pushed the Continue/Start button just past
       the visible edge no matter how big the terminal got - growing the
       window just gave the text area more space to expand into instead of
       ever revealing what came after it. Bounded height + its own internal
       scroll fixes that. */
    #body TextArea { height: 6; }
    /* _topic_banner_text() already truncates the displayed text, but this
       is a hard backstop in case even the truncated preview wraps to many
       rows on a very narrow terminal - the banner must never be able to
       push the actual conversation log out of view. */
    #topic-banner { padding: 1 2; border-bottom: solid $accent; max-height: 8; overflow-y: hidden; }
    /* height (not max-height) here since action_toggle_answer_panel()
       sets it directly at runtime to expand/collapse - unlike the topic
       banner, this one is independently scrollable (VerticalScroll, not a
       plain Static) so a long answer is reachable by scrolling rather than
       needing truncation. */
    #answer-panel { border-bottom: solid $success; }
    #answer-panel-text { padding: 1 2; }
    #log { padding: 1 2; }
    /* height: auto (not a fixed 1) - some status messages (the
       extend/stop/save-choice prompts especially) run well past one
       terminal-width line; a fixed height silently clipped the tail
       instead of wrapping. #log naturally yields space since it has no
       explicit height of its own. */
    #status { padding: 0 2; color: $text-muted; height: auto; }
    #moderator-input { margin: 0 1 1 1; }
    /* Vertical defaults to height: 1fr - it was competing with every other
       turn for a fractional share of #log's VISIBLE VIEWPORT rather than
       sizing to its own content. As more turns got mounted, everyone's
       slice kept shrinking (confirmed: an early turn's region collapsed to
       height=0 once enough later turns existed) - text wasn't scrolling
       out of view, its container was actually being crushed to nothing. */
    .turn { height: auto; margin-bottom: 1; border-left: thick $accent; padding: 0 1; }
    .turn-header.turn-a { color: $success; }
    .turn-header.turn-b { color: $warning; }
    .note { color: $text-muted; text-style: italic; padding: 0 1; }
    .final-answer { border-left: thick $success; background: $success 10%; }
    .final-answer-header { color: $success; }
    /* CollapsibleTitle defaults to width: auto - only as wide as the label
       text itself, left-anchored - while the bar you see spans the full
       container width. Clicking anywhere on that bar past the label did
       nothing. Widening the title to fill the row makes the whole thing
       clickable, matching what it visually looks like. */
    Collapsible > CollapsibleTitle { width: 1fr; }
    """

    def on_mount(self) -> None:
        self.push_screen(SourceSetupScreen(side_label="A", other_label="Model B"), callback=self._got_a)

    def _got_a(self, cfg_a: ModelConfig) -> None:
        self.cfg_a = cfg_a
        self.push_screen(SourceSetupScreen(side_label="B", other_label=cfg_a.label), callback=self._got_b)

    def _got_b(self, cfg_b: ModelConfig) -> None:
        self.cfg_b = cfg_b
        self.push_screen(TopicScreen(), callback=self._got_topic)

    def _got_topic(self, result: tuple[str, int]) -> None:
        topic, rounds = result
        self.push_screen(DialogueScreen(self.cfg_a, self.cfg_b, topic, rounds))


def run() -> None:
    DisputApp().run()


if __name__ == "__main__":
    run()
