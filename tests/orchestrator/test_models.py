import pytest
from src.orchestrator.models import resolve_model, resolve_effort, MODEL_ALIASES, EFFORT_LEVELS


def test_resolve_full_model_id_passthrough() -> None:
    assert resolve_model("claude-opus-4-7") == "claude-opus-4-7"
    assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_resolve_alias() -> None:
    assert resolve_model("opus") == "claude-opus-4-7"
    assert resolve_model("sonnet") == "claude-sonnet-4-6"
    assert resolve_model("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_alias_case_insensitive() -> None:
    assert resolve_model("OPUS") == "claude-opus-4-7"
    assert resolve_model("Sonnet") == "claude-sonnet-4-6"


def test_resolve_unknown_model_raises() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        resolve_model("gpt-5")


def test_resolve_effort_valid() -> None:
    assert resolve_effort("low") == "low"
    assert resolve_effort("medium") == "medium"
    assert resolve_effort("high") == "high"
    assert resolve_effort("max") == "max"


def test_resolve_effort_case_insensitive() -> None:
    assert resolve_effort("HIGH") == "high"
    assert resolve_effort("Max") == "max"


def test_resolve_effort_invalid_raises() -> None:
    with pytest.raises(ValueError, match="unknown effort"):
        resolve_effort("turbo")


def test_constants_consistent() -> None:
    assert "opus" in MODEL_ALIASES
    assert "sonnet" in MODEL_ALIASES
    assert EFFORT_LEVELS == {"low", "medium", "high", "max"}
