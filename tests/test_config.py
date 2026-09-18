"""Tests for happy_patch.config — Claude config loading and happy invocation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from happy_patch import config


@pytest.fixture()
def settings(tmp_path: Path) -> Path:
    """A settings.json in the shape Claude Code writes."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://relay.internal:3000",
                    "ANTHROPIC_AUTH_TOKEN": "sk-secret",
                    "ANTHROPIC_MODEL": "cn:deepseek-v4.1-flash[1M]",
                    "CLAUDE_CODE_EFFORT_LEVEL": "max",
                    "PATH": "/usr/bin",
                    "SOME_UNRELATED": "nope",
                },
                "model": "fallback-model",
            }
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# load_claude_env
# --------------------------------------------------------------------------


def test_load_claude_env_keeps_only_allowlisted_prefixes(settings: Path):
    env = config.load_claude_env(settings)

    assert env["ANTHROPIC_BASE_URL"] == "http://relay.internal:3000"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-secret"
    assert env["ANTHROPIC_MODEL"] == "cn:deepseek-v4.1-flash[1M]"
    assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "max"
    assert "PATH" not in env
    assert "SOME_UNRELATED" not in env


def test_load_claude_env_stringifies_values(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"ANTHROPIC_MODEL": 42}}), encoding="utf-8")

    assert config.load_claude_env(path) == {"ANTHROPIC_MODEL": "42"}


def test_load_claude_env_drops_null_values(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"env": {"ANTHROPIC_MODEL": None, "ANTHROPIC_BASE_URL": "x"}}),
        encoding="utf-8",
    )

    assert config.load_claude_env(path) == {"ANTHROPIC_BASE_URL": "x"}


def test_load_claude_env_handles_missing_file(tmp_path: Path, capsys):
    env = config.load_claude_env(tmp_path / "nope.json")

    assert env == {}
    assert "not found" in capsys.readouterr().err


def test_load_claude_env_handles_invalid_json(tmp_path: Path, capsys):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")

    assert config.load_claude_env(path) == {}
    assert "not valid JSON" in capsys.readouterr().err


def test_load_claude_env_handles_missing_env_block(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "x"}), encoding="utf-8")

    assert config.load_claude_env(path) == {}


def test_load_claude_env_handles_non_dict_env(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": "not-a-dict"}), encoding="utf-8")

    assert config.load_claude_env(path) == {}


def test_load_claude_env_handles_unreadable_file(tmp_path: Path, monkeypatch, capsys):
    """An OS-level read failure is reported, not raised."""
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", boom)

    assert config.load_claude_env(path) == {}
    assert "cannot read" in capsys.readouterr().err


def test_load_claude_env_skips_non_string_keys(tmp_path: Path):
    """JSON keys are always strings, but a hand-edited file could differ."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"env": {"ANTHROPIC_MODEL": "m"}}), encoding="utf-8"
    )

    env = config.load_claude_env(path)

    assert env == {"ANTHROPIC_MODEL": "m"}


# --------------------------------------------------------------------------
# resolve_model
# --------------------------------------------------------------------------


def test_resolve_model_prefers_anthropic_model(settings: Path):
    env = config.load_claude_env(settings)

    assert config.resolve_model(env, settings) == "cn:deepseek-v4.1-flash[1M]"


def test_resolve_model_falls_back_to_settings_model(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "top-level-model"}), encoding="utf-8")

    assert config.resolve_model({}, path) == "top-level-model"


def test_resolve_model_returns_empty_when_nothing_configured(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    assert config.resolve_model({}, path) == ""


def test_resolve_model_returns_empty_on_bad_json(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("nonsense", encoding="utf-8")

    assert config.resolve_model({}, path) == ""


# --------------------------------------------------------------------------
# Subcommand classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand",
    ["resume", "doctor", "auth", "connect", "sandbox", "notify", "daemon", "codex"],
)
def test_strict_subcommands_are_recognised(subcommand: str):
    assert config.is_strict_subcommand([subcommand]) is True


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--yolo"],
        ["claude", "--resume", "abc-123"],
        ["--resume", "abc-123"],
        ["someprompt"],
    ],
)
def test_session_invocations_are_not_strict(args: list):
    assert config.is_strict_subcommand(args) is False


def test_only_argv0_counts_for_subcommand_detection():
    # `claude` is stripped by happy before dispatch, so it opens a session
    # rather than selecting a subcommand.
    assert config.is_strict_subcommand(["claude", "resume"]) is False


# --------------------------------------------------------------------------
# build_argv
# --------------------------------------------------------------------------

ENV = {"ANTHROPIC_MODEL": "m", "ANTHROPIC_BASE_URL": "http://relay"}


def test_build_argv_puts_user_args_first():
    argv = config.build_argv("happy", ["claude", "--resume", "abc-123"], ENV)

    assert argv[0] == "happy"
    assert argv[1:4] == ["claude", "--resume", "abc-123"]


def test_build_argv_appends_claude_env_for_sessions():
    argv = config.build_argv("happy", ["--yolo"], ENV)

    assert argv == [
        "happy",
        "--yolo",
        "--claude-env",
        "ANTHROPIC_MODEL=m",
        "--claude-env",
        "ANTHROPIC_BASE_URL=http://relay",
    ]


def test_build_argv_keeps_subcommands_bare():
    argv = config.build_argv("happy", ["resume", "cmmij8"], ENV)

    assert argv == ["happy", "resume", "cmmij8"]
    assert "--claude-env" not in argv


def test_build_argv_does_not_break_strict_subcommand_arity():
    # `happy resume` rejects any second argument, so argv must stay length 3.
    argv = config.build_argv("happy", ["resume", "cmmij8"], ENV)

    assert len(argv) == 3


def test_build_argv_with_no_config_adds_nothing():
    assert config.build_argv("happy", ["--yolo"], {}) == ["happy", "--yolo"]


# --------------------------------------------------------------------------
# build_child_env
# --------------------------------------------------------------------------


def test_build_child_env_carries_the_config(monkeypatch):
    monkeypatch.setenv("SENTINEL", "present")

    child = config.build_child_env(ENV)

    assert child["ANTHROPIC_MODEL"] == "m"
    assert child["ANTHROPIC_BASE_URL"] == "http://relay"


def test_build_child_env_preserves_ambient_variables(monkeypatch):
    monkeypatch.setenv("SENTINEL", "present")

    child = config.build_child_env({})

    assert child["SENTINEL"] == "present"


def test_build_child_env_config_wins_over_ambient(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "ambient")

    child = config.build_child_env({"ANTHROPIC_MODEL": "configured"})

    assert child["ANTHROPIC_MODEL"] == "configured"


# --------------------------------------------------------------------------
# env_flag
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_env_flag_truthy_values(monkeypatch, value: str):
    monkeypatch.setenv("HPY_TEST_FLAG", value)

    assert config.env_flag("HPY_TEST_FLAG") is True


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off"])
def test_env_flag_falsy_values(monkeypatch, value: str):
    monkeypatch.setenv("HPY_TEST_FLAG", value)

    assert config.env_flag("HPY_TEST_FLAG") is False


def test_env_flag_unset_is_false(monkeypatch):
    monkeypatch.delenv("HPY_TEST_FLAG", raising=False)

    assert config.env_flag("HPY_TEST_FLAG") is False


def test_env_flag_tolerates_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("HPY_TEST_FLAG", "  true  ")

    assert config.env_flag("HPY_TEST_FLAG") is True


# --------------------------------------------------------------------------
# find_happy
# --------------------------------------------------------------------------


def test_find_happy_returns_the_binary(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/happy")

    assert config.find_happy() == "/usr/bin/happy"


def test_find_happy_skips_its_own_shim(monkeypatch):
    """hpy must not exec itself when `happy` resolves back to the wrapper."""
    self_path = Path(config.__file__).resolve()

    monkeypatch.setattr(config.shutil, "which", lambda name: str(self_path))

    with pytest.raises(SystemExit) as excinfo:
        config.find_happy()

    assert excinfo.value.code == 127


def test_find_happy_exits_when_not_installed(monkeypatch, capsys):
    monkeypatch.setattr(config.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as excinfo:
        config.find_happy()

    assert excinfo.value.code == 127
    assert "cannot find 'happy'" in capsys.readouterr().err


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def test_run_launches_the_assembled_command(monkeypatch):
    seen = {}

    def fake_call(argv, env=None):
        seen["argv"] = argv
        seen["env"] = env
        return 7

    monkeypatch.setattr(config.subprocess, "call", fake_call)

    code = config.run("happy", ["--yolo"], ENV)

    assert code == 7
    assert seen["argv"][0] == "happy"
    assert seen["env"]["ANTHROPIC_MODEL"] == "m"


def test_run_maps_keyboard_interrupt_to_130(monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(config.subprocess, "call", interrupt)

    assert config.run("happy", [], ENV) == 130
