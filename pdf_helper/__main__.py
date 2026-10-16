"""Entry point: pywebview owns the main thread, the tray icon runs detached."""

import threading

from .app import safe_read_pass
from .tray import ForegroundTracker, build_icon, find_topmost_window


def _start_tray() -> None:
    import webview

    tracker = ForegroundTracker()
    tracker.start()

    def on_read() -> None:
        # The last real foreground window; failing that, whatever is on top of the Z-order.
        candidate = tracker.candidate or find_topmost_window()
        threading.Thread(
            target=safe_read_pass, args=(candidate,), name="read-pass", daemon=True
        ).start()

    def on_quit() -> None:
        icon.stop()
        tracker.stop()
        for window in list(webview.windows):
            window.destroy()

    icon = build_icon(on_read, on_quit)
    icon.run_detached()


def main() -> None:
    import webview

    # A hidden placeholder keeps the webview loop alive while no document is open.
    webview.create_window("Readable Document", html="<p></p>", hidden=True)
    webview.start(func=_start_tray)


if __name__ == "__main__":
    main()
