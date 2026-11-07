"""preflight.py must cost nothing by default: no Gemini call unless --live (Agent 2)."""
import importlib.util
from pathlib import Path

import pytest

from app.config import load_settings

spec = importlib.util.spec_from_file_location("preflight", Path(__file__).parent.parent / "scripts" / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def no_net(monkeypatch):
    calls = []

    async def boom(*a, **k):
        calls.append(a)
        raise AssertionError("Gemini must not be called without --live")

    monkeypatch.setattr(preflight, "classify_text", boom)
    monkeypatch.setattr(preflight, "check_twilio", lambda s: None)
    return calls


def test_default_skips_gemini_call(monkeypatch, no_net, capsys):
    monkeypatch.setattr(preflight, "load_settings",
                        lambda: load_settings(gemini_api_key="k-secret-value", phones_file="__none__.json"))
    assert preflight.main([]) == 0
    out = capsys.readouterr().out
    assert "Live call skipped" in out and "k-secret-value" not in out
    assert no_net == []


def test_missing_key_exits_1(monkeypatch, no_net):
    monkeypatch.setattr(preflight, "load_settings", lambda: load_settings(gemini_api_key="", phones_file="__none__.json"))
    assert preflight.main([]) == 1
    assert preflight.main(["--live"]) == 1
    assert no_net == []
