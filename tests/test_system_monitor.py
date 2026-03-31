"""Tests for claude_notch.system_monitor — SystemMonitor, process cache."""

from unittest.mock import patch, MagicMock


from claude_notch.system_monitor import SystemMonitor, _find_claude_processes


def test_ram_returns_dict():
    """get_ram() must return a dict with pct, used_gb, total_gb."""
    ram = SystemMonitor.get_ram()
    assert isinstance(ram, dict)
    for key in ("pct", "used_gb", "total_gb"):
        assert key in ram, f"Missing key '{key}' in RAM dict"


def test_cpu_returns_float():
    """get_cpu() must return a float (possibly 0.0 on first call)."""
    cpu = SystemMonitor.get_cpu()
    assert isinstance(cpu, float)


def test_process_cache():
    """_find_claude_processes should return a list (may be empty if no Claude running)."""
    # Patch subprocess.run so we don't actually call PowerShell during tests
    fake_result = MagicMock()
    fake_result.stdout = ""
    fake_result.returncode = 0

    # Reset the cache so our patched call is actually exercised
    import claude_notch.system_monitor as sm_mod
    sm_mod._cached_claude_processes_ts = 0.0

    with patch("claude_notch.system_monitor.subprocess.run", return_value=fake_result):
        result = _find_claude_processes()
    assert isinstance(result, list)
