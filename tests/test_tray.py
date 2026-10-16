from pdf_helper.tray import accept_window, make_icon_image, pick_topmost
from pdf_helper.window_finder import Candidate


def test_pick_topmost_skips_shell_hidden_and_own_windows():
    entries = [  # Z-order, top first: (hwnd, title, cls, pid, visible)
        (1, "", "Mozilla_firefox_RemoteWindow", 10, False),
        (2, "Taskbar", "Shell_TrayWnd", 20, True),
        (3, "Readable: x", "Chrome_WidgetWin_1", 99, True),
        (4, "report.pdf - Firefox", "MozillaWindowClass", 10, True),
        (5, "Other", "X", 30, True),
    ]
    assert pick_topmost(entries, own_pid=99) == Candidate(4, "report.pdf - Firefox", 10, "MozillaWindowClass")
    assert pick_topmost(entries[:3], own_pid=99) is None


def test_accept_window_rules():
    assert accept_window("report.pdf - Edge", "Chrome_WidgetWin_1", 10, 99, True)
    assert not accept_window("", "Chrome_WidgetWin_1", 10, 99, True)
    assert not accept_window("Start", "Windows.UI.Core.CoreWindow", 10, 99, True)
    assert not accept_window("Taskbar", "Shell_TrayWnd", 10, 99, True)
    assert not accept_window("Me", "X", 99, 99, True)
    assert not accept_window("Hidden", "X", 10, 99, False)


def test_icon_image_is_64px():
    assert make_icon_image().size == (64, 64)
