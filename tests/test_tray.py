from pdf_helper.tray import ReadGate, accept_window, make_icon_image, pick_topmost
from pdf_helper.window_finder import Candidate


def test_read_gate_ignores_second_click_of_a_double_click():
    gate = ReadGate(debounce_seconds=1.0)
    assert gate.try_acquire(now=10.0)
    gate.release()
    assert not gate.try_acquire(now=10.2)  # second WM_LBUTTONUP of a double-click
    assert gate.try_acquire(now=11.5)


def test_read_gate_ignores_clicks_while_a_pass_is_running():
    gate = ReadGate(debounce_seconds=1.0)
    assert gate.try_acquire(now=10.0)
    assert not gate.try_acquire(now=30.0)  # still running
    gate.release()
    assert gate.try_acquire(now=31.5)


def test_pick_topmost_skips_shell_hidden_and_own_windows():
    entries = [  # Z-order, top first: (hwnd, title, cls, pid, visible, width, height)
        (1, "", "Mozilla_firefox_RemoteWindow", 10, False, 0, 0),
        (2, "Taskbar", "Shell_TrayWnd", 20, True, 2560, 48),
        (3, "Readable: x", "Chrome_WidgetWin_1", 99, True, 960, 1000),
        (4, "report.pdf - Firefox", "MozillaWindowClass", 10, True, 1280, 900),
        (5, "Other", "X", 30, True, 800, 600),
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


def test_accept_window_rejects_windows_11_shell_flyouts():
    # Opening the tray overflow to reach the icon makes this explorer.exe window foreground.
    assert not accept_window("System tray overflow window.", "TopLevelWindowForOverflowXamlIsland", 10, 99, True)
    assert not accept_window("", "Shell_SecondaryTrayWnd", 10, 99, True)
    assert not accept_window("Start", "XamlExplorerHostIslandWindow", 10, 99, True)


def test_accept_window_rejects_windows_too_small_to_read():
    # The capture refuses anything under 200x200, so the tracker must not record it either.
    assert not accept_window("Some flyout", "Unknown", 10, 99, True, width=234, height=114)
    assert not accept_window("Narrow", "Unknown", 10, 99, True, width=150, height=900)
    assert accept_window("report.pdf - Edge", "Chrome_WidgetWin_1", 10, 99, True, width=800, height=600)


def test_pick_topmost_skips_small_windows():
    entries = [
        (1, "System tray overflow window.", "Unknown", 10, True, 234, 114),
        (2, "report.pdf - Edge", "Chrome_WidgetWin_1", 10, True, 1280, 900),
    ]
    assert pick_topmost(entries, own_pid=99) == Candidate(2, "report.pdf - Edge", 10, "Chrome_WidgetWin_1")


def test_icon_image_is_64px():
    assert make_icon_image().size == (64, 64)
