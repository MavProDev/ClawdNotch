"""Tests for TokenAggregator — real token usage from JSONL files."""

import json
import time

import pytest


@pytest.fixture()
def mock_claude_dir(tmp_path, monkeypatch):
    """Create a fake ~/.claude/projects/ with JSONL files."""
    projects_dir = tmp_path / ".claude" / "projects"
    project_hash = projects_dir / "C--fake-project"
    project_hash.mkdir(parents=True)

    import claude_notch.usage as usage_mod
    monkeypatch.setattr(usage_mod.TokenAggregator, "CLAUDE_PROJECTS_DIR", projects_dir)
    return project_hash


def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _assistant_msg(input_tok, output_tok, ts="2026-03-31T12:00:00.000Z",
                   cache_read=0, cache_write=0):
    return {
        "message": {
            "role": "assistant",
            "usage": {
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
        "timestamp": ts,
    }


def test_get_today_parses_jsonl(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    session_id = "abc-123-def"
    jsonl_file = mock_claude_dir / f"{session_id}.jsonl"
    today = time.strftime("%Y-%m-%d")
    _write_jsonl(jsonl_file, [
        _assistant_msg(100, 200, f"{today}T10:00:00.000Z"),
        _assistant_msg(300, 400, f"{today}T11:00:00.000Z"),
    ])

    agg = TokenAggregator(cache_ttl_seconds=0)
    result = agg.get_today()
    assert result["input"] == 400
    assert result["output"] == 600
    assert result["total"] == 1000


def test_get_session_finds_by_filename(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    session_id = "sess-456-ghi"
    jsonl_file = mock_claude_dir / f"{session_id}.jsonl"
    _write_jsonl(jsonl_file, [
        _assistant_msg(500, 1000, "2026-03-31T12:00:00.000Z", cache_read=200),
        _assistant_msg(100, 200, "2026-03-31T13:00:00.000Z"),
    ])

    agg = TokenAggregator(cache_ttl_seconds=0)
    result = agg.get_session(session_id)
    assert result["input"] == 600
    assert result["output"] == 1200
    assert result["cache_read"] == 200
    assert result["total"] == 2000


def test_get_session_empty_for_unknown(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    agg = TokenAggregator(cache_ttl_seconds=0)
    result = agg.get_session("nonexistent-session")
    assert result["total"] == 0


def test_get_session_caches_result(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    session_id = "cached-sess"
    jsonl_file = mock_claude_dir / f"{session_id}.jsonl"
    _write_jsonl(jsonl_file, [_assistant_msg(100, 200, "2026-03-31T12:00:00.000Z")])

    agg = TokenAggregator(cache_ttl_seconds=60)
    r1 = agg.get_session(session_id)
    assert r1["total"] == 300

    # Modify the file — cached result should be returned
    _write_jsonl(jsonl_file, [_assistant_msg(999, 999, "2026-03-31T12:00:00.000Z")])
    r2 = agg.get_session(session_id)
    assert r2["total"] == 300  # still cached


def test_skips_lines_without_usage(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    session_id = "mixed-content"
    jsonl_file = mock_claude_dir / f"{session_id}.jsonl"
    today = time.strftime("%Y-%m-%d")
    entries = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        _assistant_msg(100, 200, f"{today}T10:00:00.000Z"),
        {"type": "system", "subtype": "hook_summary"},
    ]
    _write_jsonl(jsonl_file, entries)

    agg = TokenAggregator(cache_ttl_seconds=0)
    result = agg.get_today()
    assert result["total"] == 300


def test_get_month_total(mock_claude_dir):
    from claude_notch.usage import TokenAggregator

    session_id = "monthly-test"
    jsonl_file = mock_claude_dir / f"{session_id}.jsonl"
    month = time.strftime("%Y-%m")
    _write_jsonl(jsonl_file, [
        _assistant_msg(1000, 2000, f"{month}-01T10:00:00.000Z"),
        _assistant_msg(3000, 4000, f"{month}-15T10:00:00.000Z"),
    ])

    agg = TokenAggregator(cache_ttl_seconds=0)
    total = agg.get_month_total()
    assert total == 10000
