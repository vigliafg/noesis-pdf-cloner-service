"""Applicazione Textual: CSS, schermata iniziale e chiusura ordinata."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ..config import Settings
from ..storage import Storage
from .screens import HomeScreen
from .runner import TuiJobRunner


class NoesisTUI(App):
    """TUI del cloner: client locale della pipeline (nessun server)."""

    TITLE = "Noesis PDF Cloner"
    SUB_TITLE = "TUI · traduzione PDF con layout preservato"
    BINDINGS = [Binding("ctrl+q", "quit_app", "Esci")]

    CSS = """
    Screen { background: $surface; }

    #home, #wizard, #run { padding: 1 2; height: 1fr; }
    #home-title { text-style: bold; padding-bottom: 1; }
    #home-hint { color: $text-muted; padding-bottom: 1; }
    #jobs { height: 1fr; }
    #wizard { height: 1fr; }
    #wizard-title { text-style: bold; padding-bottom: 1; color: $accent; }
    .step { height: auto; padding-bottom: 1; }
    .step Label { padding-top: 1; }
    .hint { color: $text-muted; }
    #llm-box { height: auto; }
    #wizard-nav, #run-nav { height: auto; padding-top: 1; }
    #wizard-nav Button, #run-nav Button { margin-right: 2; }
    #run-title { text-style: bold; padding-bottom: 1; }
    #run-status { padding: 1 0; }
    #run-grid { color: $text-muted; }
    #log { height: 1fr; border: round $primary-darken-2; padding: 0 1; }
    #doctor { padding: 1 2; width: 90; height: auto; background: $panel; border: round $accent; }
    #doctor-title { text-style: bold; padding-bottom: 1; }
    #doctor-body { padding-bottom: 1; }
    """

    def __init__(self, settings: Settings, storage: Storage) -> None:
        super().__init__()
        self.settings = settings
        self.storage = storage
        # Runner del job in corso (impostato da RunScreen): serve alla chiusura
        # per annullare ed evitare un motore orfano.
        self.active_runner: TuiJobRunner | None = None

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    async def action_quit(self) -> None:  # Ctrl+C / uscita standard
        self._drain_active_job()
        self.exit()

    def action_quit_app(self) -> None:  # Ctrl+Q
        self._drain_active_job()
        self.exit()

    def _drain_active_job(self) -> None:
        runner = self.active_runner
        if runner is None or runner.done.is_set():
            return
        runner.cancel()
        # Attesa breve: il cancel uccide il subprocess entro ~1 s; oltre, meglio
        # uscire (la pagina in corso resta in cache al prossimo giro).
        runner.join(5.0)
