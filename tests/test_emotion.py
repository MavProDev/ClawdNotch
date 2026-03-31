"""Tests for the EmotionEngine (claude_notch.sessions.EmotionEngine)."""

import pytest
from claude_notch.sessions import EmotionEngine


@pytest.fixture()
def engine():
    return EmotionEngine()


SID = "emo-test-1"


def test_positive_keywords(engine):
    """Repeated positive prompts should push the emotion to happy."""
    # The EmotionEngine accumulates scores — a single prompt rarely crosses
    # the 0.6 threshold for happy.  We send several positive prompts.
    for _ in range(5):
        result = engine.process(SID, "This is awesome, everything works perfectly and is great!")
    assert result == "happy", f"Expected 'happy' after repeated positives, got '{result}'"


def test_negative_keywords(engine):
    """Repeated negative prompts should push the emotion to sad (not yet sob)."""
    sid = "neg-test"
    for _ in range(3):
        result = engine.process(sid, "The build is broken and there's an error")
    assert result == "sad", f"Expected 'sad' after repeated negatives, got '{result}'"


def test_profanity_positive(engine):
    """'hell yeah' (positive profanity) after several reps should produce happy."""
    sid = "prof-test"
    for _ in range(5):
        result = engine.process(sid, "hell yeah that deploy was smooth and amazing")
    assert result == "happy", f"Expected 'happy', got '{result}'"


def test_sob_threshold(engine):
    """Repeated negative prompts should push the emotion into 'sob'."""
    for _ in range(15):
        result = engine.process(SID, "this is terrible broken awful crash error hate")
    assert result == "sob", f"Expected 'sob' after repeated negatives, got '{result}'"


def test_short_prompt_neutral(engine):
    """Prompts shorter than 10 chars should resolve to neutral."""
    result = engine.process(SID, "ok")
    assert result == "neutral"


def test_decay_reduces_scores(engine):
    """decay_all should reduce all accumulated scores toward zero."""
    engine.process(SID, "This is absolutely amazing and fantastic!!!")
    before = dict(engine._scores.get(SID, {}))

    engine.decay_all()
    after = engine._scores.get(SID, {})

    # Every score category should be lower after decay
    for key in before:
        assert after[key] <= before[key], (
            f"Score '{key}' did not decay: {before[key]} -> {after[key]}"
        )
