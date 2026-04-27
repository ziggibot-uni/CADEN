from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static
from textual.containers import Vertical

import structlog
from .. import diag
logger = structlog.get_logger()


def render_terminal_error_banner(exception: Exception, context: str) -> str:
    """Render the same error-banner wording for terminal boot failures."""
    return f"Subsystem Failed: {context}\n{exception}"

class ErrorBanner(ModalScreen[None]):
    """Modal banner that pops up on a CadenError, failing loudly per spec."""
    
    CSS = """
    ErrorBanner {
        align: center middle;
    }
    #dialog {
        padding: 1 2;
        width: 60%;
        height: auto;
        border: thick $error;
        background: $surface;
    }
    #details {
        margin-top: 1;
        margin-bottom: 1;
        color: $text-muted;
    }
    """
    
    def __init__(self, exception: Exception, context: str) -> None:
        super().__init__()
        self.exception = exception
        self.err_context = context
        diag.log("caden_error", f"context={context}\nerror={exception}")
        logger.error("subsystem_failed", context=context, exc_info=exception)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Subsystem Failed: {self.err_context}")
            yield Label(str(self.exception), id="details")
            yield Button("Copy Details", variant="primary", id="copy")
            yield Button("Dismiss", variant="default", id="dismiss")
            
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy":
            self.app.copy_to_clipboard(f"Context: {self.err_context}\nError: {self.exception}")
            self.notify("Details copied to clipboard", severity="information")
        elif event.button.id == "dismiss":
            self.dismiss(None)
