"""Tests for happy_patch.cli — the two entry points."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from happy_patch import bundle, cli
from happy_patch import config as config_mod


@pytest.fixture()
def spy(monkeypatch):
    """Capture the fully assembled command line at the subprocess boundary.

    `cli.hpy_main` delegates to `config.run`, which assembles argv and calls
    subprocess; intercepting there is the only place the real command line is
    observable.
    """
    captured = {}

    def fake_call(argv, env=None):
        captured["argv"] = argv
        captured["env"] = env
        return 0

    monkeypatch.setattr(config_mod.subprocess, "call", fake_call)
    monkeypatch.setattr(cli, "find_happy", lambda: "happy")
    return captured


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch):
    """A fake install: one patchable bundle plus a settings file."""
    from conftest import MINIMAL_BUNDLE

    bundle_dir = tmp_path / "dist"
    bundle_dir.mkdir()
    real = bundle_dir / "index-abc.mjs"
    real.write_text(MINIMAL_BUNDLE, encoding="utf-8")

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"env": {"ANTHROPIC_MODEL": "test-model-1m"}}), encoding="utf-8"
    )

    monkeypatch.setattr(bundle, "BUNDLE_DIR", bundle_dir)
    monkeypatch.setattr(cli, "SETTINGS_PATH", settings)
    return {"bundle": real, "settings": settings}


# --------------------------------------------------------------------------
# hpy_main
# --------------------------------------------------------------------------


def test_hpy_patches_then_launches(workspace, spy):
    code = cli.hpy_main(["--yolo"])

    assert code == 0
    text = workspace["bundle"].read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) == "test-model-1m"

    assert spy["argv"][0] == "happy"
    assert spy["argv"][1] == "--yolo"
    assert "--claude-env" in spy["argv"]
    assert spy["env"]["ANTHROPIC_MODEL"] == "test-model-1m"


def test_hpy_skips_patching_when_disabled(workspace, monkeypatch):
    monkeypatch.setattr(cli, "find_happy", lambda: "happy")
    monkeypatch.setattr(cli, "run", lambda *a, **k: 0)
    monkeypatch.setenv("HPY_NO_PATCH", "1")

    cli.hpy_main(["--yolo"])

    text = workspace["bundle"].read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) is None


def test_hpy_survives_patcher_failure(workspace, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("patch exploded")

    monkeypatch.setattr(cli.bundle, "ensure_patched", boom)
    monkeypatch.setattr(cli, "find_happy", lambda: "happy")
    monkeypatch.setattr(cli, "run", lambda *a, **k: 0)

    assert cli.hpy_main(["--yolo"]) == 0
    assert "patching failed" in capsys.readouterr().err


def test_hpy_reports_incomplete_patch(workspace, monkeypatch, capsys):
    monkeypatch.setattr(cli.bundle, "ensure_patched", lambda *a, **k: False)
    monkeypatch.setattr(cli, "find_happy", lambda: "happy")
    monkeypatch.setattr(cli, "run", lambda *a, **k: 0)

    cli.hpy_main(["--yolo"])

    assert "patch incomplete" in capsys.readouterr().err


def test_hpy_forwards_exit_code(workspace, monkeypatch):
    monkeypatch.setattr(cli, "find_happy", lambda: "happy")
    monkeypatch.setattr(cli, "run", lambda *a, **k: 42)

    assert cli.hpy_main(["--yolo"]) == 42


def test_hpy_passes_subcommands_through_without_flags(workspace, spy):
    """Strict subcommands must reach happy with no injected flags."""
    cli.hpy_main(["resume", "cmmij8"])

    assert spy["argv"] == ["happy", "resume", "cmmij8"]
    assert "--claude-env" not in spy["argv"]
    # The config still reaches the subprocess through the environment.
    assert spy["env"]["ANTHROPIC_MODEL"] == "test-model-1m"


def test_hpy_adds_flags_for_session_invocations(workspace, spy):
    cli.hpy_main(["claude", "--resume", "abc-123"])

    assert spy["argv"][:4] == ["happy", "claude", "--resume", "abc-123"]
    assert "--claude-env" in spy["argv"]


# --------------------------------------------------------------------------
# patch_main
# --------------------------------------------------------------------------


def test_patch_main_status_reports_state(workspace, capsys):
    code = cli.patch_main(["--status"])

    assert code == 0
    assert "index-abc.mjs: not patched" in capsys.readouterr().out


def test_patch_main_applies_a_model(workspace, capsys):
    code = cli.patch_main(["--model", "forced-model"])

    assert code == 0
    text = workspace["bundle"].read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) == "forced-model"
    assert "index-abc.mjs: applied" in capsys.readouterr().err


def test_patch_main_reports_applied_model(workspace, capsys):
    cli.patch_main(["--model", "forced-model"])
    capsys.readouterr()

    cli.patch_main(["--status"])

    assert "index-abc.mjs: forced-model" in capsys.readouterr().out


def test_patch_main_unpatches(workspace, capsys):
    cli.patch_main(["--model", "forced-model"])
    capsys.readouterr()

    code = cli.patch_main(["--unpatch"])

    assert code == 0
    assert "restored 1 bundle(s)" in capsys.readouterr().out
    text = workspace["bundle"].read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) is None


def test_patch_main_path_prints_bundle_dir(workspace, capsys):
    code = cli.patch_main(["--path"])

    assert code == 0
    assert str(bundle.BUNDLE_DIR) in capsys.readouterr().out


def test_patch_main_status_handles_missing_bundles(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path / "gone")

    assert cli.patch_main(["--status"]) == 0
    assert "no bundles found" in capsys.readouterr().out


def test_patch_main_requires_an_action():
    with pytest.raises(SystemExit):
        cli.patch_main([])


def test_patch_main_rejects_conflicting_actions():
    with pytest.raises(SystemExit):
        cli.patch_main(["--status", "--unpatch"])


# --------------------------------------------------------------------------
# hpy_main - verbose reporting
# --------------------------------------------------------------------------


def test_hpy_verbose_reports_forwarded_config(workspace, spy, monkeypatch, capsys):
    monkeypatch.setenv("HPY_VERBOSE", "1")
    monkeypatch.setattr(cli, "VERBOSE", True)

    cli.hpy_main(["--yolo"])

    err = capsys.readouterr().err
    assert "forwarding 1 env vars" in err
    assert "model to force: test-model-1m" in err
    assert "ANTHROPIC_MODEL=test-model-1m" in err


def test_hpy_verbose_redacts_secrets(workspace, spy, monkeypatch, capsys):
    workspace["settings"].write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_MODEL": "m",
                    "ANTHROPIC_AUTH_TOKEN": "sk-do-not-print-me",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "VERBOSE", True)

    cli.hpy_main(["--yolo"])

    err = capsys.readouterr().err
    assert "ANTHROPIC_AUTH_TOKEN=<redacted>" in err
    assert "sk-do-not-print-me" not in err


def test_hpy_verbose_logs_subcommand_routing(workspace, spy, monkeypatch, capsys):
    monkeypatch.setattr(cli, "VERBOSE", True)

    cli.hpy_main(["doctor"])

    assert "config passed via environment only" in capsys.readouterr().err


def test_hpy_verbose_reports_skipped_patch(workspace, spy, monkeypatch, capsys):
    monkeypatch.setattr(cli, "VERBOSE", True)
    monkeypatch.setenv("HPY_NO_PATCH", "1")

    cli.hpy_main(["--yolo"])

    assert "patching disabled" in capsys.readouterr().err


def test_hpy_verbose_reports_missing_model(workspace, spy, monkeypatch, capsys):
    """With no model anywhere, the patcher is skipped and says so."""
    workspace["settings"].write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(cli, "VERBOSE", True)

    cli.hpy_main(["--yolo"])

    err = capsys.readouterr().err
    assert "no model configured; skipping patch" in err
    assert "model to force: (none)" in err


def test_hpy_skips_patch_when_no_model_configured(workspace, spy):
    workspace["settings"].write_text(json.dumps({}), encoding="utf-8")

    cli.hpy_main(["--yolo"])

    text = workspace["bundle"].read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) is None
