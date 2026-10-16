"""Entry point: pywebview owns the main thread, the tray icon runs detached."""

import threading

from .app import safe_read_pass
from .errors import log_exception, show_error
from .transcription_cache import clear as clear_cache
from .tray import ForegroundTracker, ReadGate, build_icon, clear_cache_message, find_topmost_window
from .viewer import open_saved, pick_saved_file


def _start_tray() -> None:
    import webview

    tracker = ForegroundTracker()
    tracker.start()
    gate = ReadGate()

    def on_read() -> None:
        if not gate.try_acquire():
            return  # a pass is already running, or this is the second half of a double-click
        # The last real foreground window; failing that, whatever is on top of the Z-order.
        candidate = tracker.candidate or find_topmost_window()
        try:
            icon.notify("Reading with Claude… this can take a minute for long documents.", "Readable Document")
        except Exception:  # notifications are best effort
            pass

        def run() -> None:
            try:
                safe_read_pass(candidate)
            finally:
                gate.release()

        threading.Thread(target=run, name="read-pass", daemon=True).start()

    def on_open() -> None:
        path = pick_saved_file()
        if path is None:
            return
        try:
            open_saved(path)
        except Exception as exc:  # noqa: BLE001 - the tray must survive anything
            log_exception(exc)
            show_error(f"Could not open {path.name}: {exc}")

    def on_clear_cache() -> None:
        try:
            message = clear_cache_message(clear_cache())
        except Exception as exc:  # noqa: BLE001 - the tray must survive anything
            log_exception(exc)
            show_error(f"Could not clear the transcription cache: {exc}")
            return
        try:
            icon.notify(message, "Readable Document")
        except Exception:  # notifications are best effort
            pass

    def on_quit() -> None:
        icon.stop()
        tracker.stop()
        for window in list(webview.windows):
            window.destroy()

    icon = build_icon(on_read, on_quit, on_clear_cache, on_open)
    icon.run_detached()


def main() -> None:
    import webview

    from .dotenv import load_dotenv

    load_dotenv()  # ANTHROPIC_API_KEY from the project's .env, unless already set
    # A hidden placeholder keeps the webview loop alive while no document is open.
    webview.create_window("Readable Document", html="<p></p>", hidden=True)
    webview.start(func=_start_tray)


if __name__ == "__main__":
    main()
