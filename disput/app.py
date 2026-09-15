"""Disput's TUI: setup wizard (pick/add a source, discover its models,
pick one, set a label + system prompt - twice, once per side) followed by
a live dialogue screen."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

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
from .client import ModelConfig, ModelReply, call_model, list_models, make_client, save_code_blocks

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

OUTPUT_DIR = Path("dialogue_output")
TRANSCRIPTS_DIR = Path("transcripts")
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
        yield Static(f" Setting up Model {self.side_label} ", id="step-title")
        yield VerticalScroll(id="body")
        yield Footer()

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
            TextArea(DEFAULT_TOPIC, id="topic-area"),
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
        topic = self.query_one("#topic-area", TextArea).text.strip() or DEFAULT_TOPIC
        rounds_raw = self.query_one("#rounds-input", Input).value.strip()
        rounds = int(rounds_raw) if rounds_raw.isdigit() and int(rounds_raw) > 0 else DEFAULT_ROUNDS
        self.dismiss((topic, rounds))


# ============================== Live dialogue ================================


class DialogueScreen(Screen):
    BINDINGS = [
        ("ctrl+p", "toggle_pause", "Pause/Resume"),
        ("ctrl+q", "quit_app", "Quit & Save"),
    ]

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

        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        yield Static(f"[b]Topic:[/b] {self.topic}", id="topic-banner")
        yield VerticalScroll(id="log")
        yield Static("", id="status")
        yield Input(placeholder="Type a moderator note and press Enter (or just watch it run)...", id="moderator-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#moderator-input", Input).focus()
        self.take_turn()

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

        self.app.call_from_thread(self.set_status, f"Turn {turn_no}: {cfg.label} thinking…")
        try:
            reply = call_model(client, cfg, history)
        except Exception as exc:  # noqa: BLE001 - network/backend error, surface and pause rather than crash
            self.app.call_from_thread(self.handle_turn_error, exc)
            return
        self.app.call_from_thread(self.handle_turn_result, turn_no, current, cfg, reply)

    def handle_turn_error(self, exc: Exception) -> None:
        self.turn_in_progress = False
        self.paused = True
        self.mount_note(f"[red]Error calling model: {exc}[/red]")
        self.set_status("Paused after an error. Fix the issue, then press ctrl+p to retry.")

    def handle_turn_result(self, turn_no: int, current: str, cfg: ModelConfig, reply: ModelReply) -> None:
        self.turn = turn_no
        other = "B" if current == "A" else "A"

        self.mount_turn_widget(turn_no, current, cfg, reply)

        if reply.code_blocks:
            paths = save_code_blocks(reply.code_blocks, self.code_dir, turn_no, cfg.label)
            self.mount_note(f"💾 saved {len(paths)} code file(s): " + ", ".join(p.name for p in paths))

        self.history_a.append({"role": "assistant" if current == "A" else "user", "content": reply.final})
        self.history_b.append({"role": "assistant" if current == "B" else "user", "content": reply.final})

        self._append_transcript_turn(turn_no, cfg, reply)
        if reply.thinking:
            self._append_reasoning(turn_no, cfg.label, reply.thinking)

        self.current = other
        self.turn_in_progress = False

        if self.turn >= self.total_rounds:
            self.awaiting_extend = True
            self.set_status(
                f"Reached {self.total_rounds} turns. Type a number below to extend, or anything else to stop."
            )
            return

        self.set_status("")
        if not self.paused:
            self.set_timer(0.5, self.take_turn)

    # -- moderator / extend input -------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "moderator-input":
            return
        value = event.value.strip()
        event.input.value = ""

        if self.awaiting_extend:
            if value.isdigit() and int(value) > 0:
                self.total_rounds += int(value)
                self.awaiting_extend = False
                self.mount_note(f"Extending — now running to turn {self.total_rounds}.")
                self.set_status("")
                self.take_turn()
            else:
                self.action_quit_app()
            return

        if value:
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
        self._write_transcript()
        self.app.exit()

    # -- UI helpers ------------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

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
    CSS = """
    #step-title { padding: 1 2; text-style: bold; }
    #body { padding: 1 2; height: auto; }
    #topic-banner { padding: 1 2; border-bottom: solid $accent; }
    #log { padding: 1 2; }
    #status { padding: 0 2; color: $text-muted; height: 1; }
    #moderator-input { margin: 0 1 1 1; }
    .turn { margin-bottom: 1; border-left: thick $accent; padding: 0 1; }
    .turn-header.turn-a { color: $success; }
    .turn-header.turn-b { color: $warning; }
    .note { color: $text-muted; text-style: italic; padding: 0 1; }
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
