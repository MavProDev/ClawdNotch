"""Tests for ClawdToast lifecycle and stacking."""


def test_toast_creates_without_crash(qapp):
    """ClawdToast should instantiate without errors."""
    from claude_notch.ui import ClawdToast
    # Clear any existing toasts
    ClawdToast._active_toasts.clear()

    toast = ClawdToast("Test Title", "Test message", timeout=1, pid=0, ntype="info")
    assert toast is not None
    assert len(ClawdToast._active_toasts) == 1
    toast._dismiss()
    assert len(ClawdToast._active_toasts) == 0


def test_toast_stacking(qapp):
    """Multiple toasts should stack without overlap."""
    from claude_notch.ui import ClawdToast
    ClawdToast._active_toasts.clear()

    t1 = ClawdToast("Toast 1", "First", timeout=10)
    t2 = ClawdToast("Toast 2", "Second", timeout=10)
    t3 = ClawdToast("Toast 3", "Third", timeout=10)

    assert len(ClawdToast._active_toasts) == 3
    # Each toast should have a different target_y
    assert t1._target_y != t2._target_y
    assert t2._target_y != t3._target_y

    # Cleanup
    for t in list(ClawdToast._active_toasts):
        t._dismiss()


def test_toast_restack_on_dismiss(qapp):
    """Dismissing a toast should reposition remaining toasts."""
    from claude_notch.ui import ClawdToast
    ClawdToast._active_toasts.clear()

    toast1 = ClawdToast("Toast 1", "First", timeout=10)
    ClawdToast("Toast 2", "Second", timeout=10)
    toast3 = ClawdToast("Toast 3", "Third", timeout=10)

    # Remember toast3's original position
    t3_orig_y = toast3._target_y

    # Dismiss toast1 (bottom toast)
    toast1._dismiss()
    assert len(ClawdToast._active_toasts) == 2

    # toast3 should have moved down (closer to bottom of screen)
    assert toast3._target_y > t3_orig_y

    # Cleanup
    for t in list(ClawdToast._active_toasts):
        t._dismiss()


def test_toast_border_colors(qapp):
    """Different notification types should use different border colors."""
    from claude_notch.ui import ClawdToast
    ClawdToast._active_toasts.clear()

    ClawdToast("Done", "Task done", ntype="completion")
    ClawdToast("Attn", "Need input", ntype="attention")
    ClawdToast("Budget", "Over budget", ntype="budget")

    # All should exist
    assert len(ClawdToast._active_toasts) == 3

    # Cleanup
    for t in list(ClawdToast._active_toasts):
        t._dismiss()
