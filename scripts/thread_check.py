"""Spike: can pywebview own the main thread while pystray runs detached?

Run it: a tray icon appears. Its "Open window" item must open a second
webview window; "Quit" must stop the icon and let the app exit.
Pass --auto to exercise the same path without clicking: the script opens the
second window itself after 2 seconds and quits after 5.
"""

import sys
import threading
import time

import pystray
import webview
from PIL import Image, ImageDraw

AUTO = "--auto" in sys.argv


def icon_image() -> Image.Image:
    img = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(img).rectangle((16, 8, 48, 56), outline="black", width=4)
    return img


def open_window(icon=None, item=None) -> None:
    webview.create_window("Second", html="<h1>It works</h1>")
    print("second window created", flush=True)


def quit_app(icon, item=None) -> None:
    icon.stop()
    for window in list(webview.windows):
        window.destroy()
    print("quit", flush=True)


def start_tray() -> None:
    icon = pystray.Icon(
        "thread-check",
        icon_image(),
        "Thread check",
        menu=pystray.Menu(
            pystray.MenuItem("Open window", open_window, default=True),
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    icon.run_detached()
    print("tray running detached", flush=True)
    if AUTO:
        def auto():
            time.sleep(2)
            open_window()
            time.sleep(3)
            quit_app(icon)
        threading.Thread(target=auto, daemon=True).start()


if __name__ == "__main__":
    webview.create_window("placeholder", html="<p>hidden</p>", hidden=True)
    webview.start(func=start_tray)
    print("webview loop exited", flush=True)
