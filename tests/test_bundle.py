"""Tests for happy_patch.bundle — the patcher itself."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import MINIMAL_BUNDLE
from happy_patch import bundle

# The fake bundle lives in conftest so test_cli can share it verbatim.
FAKE_BUNDLE = MINIMAL_BUNDLE

MODEL = "cn:deepseek-v4.1-flash[1M]"


@pytest.fixture()
def fake_bundle(tmp_path: Path) -> Path:
    """A writable fake bundle laid out like the real one."""
    path = tmp_path / "index-abc123.mjs"
    path.write_text(FAKE_BUNDLE, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Anchor matching
# --------------------------------------------------------------------------


def test_every_site_matches_the_fake_bundle():
    for description, pattern, _ in bundle.SITES:
        assert pattern.search(FAKE_BUNDLE), f"anchor not found: {description}"


def test_sites_are_matched_exactly_once(fake_bundle: Path):
    text = fake_bundle.read_text(encoding="utf-8")
    for description, pattern, _ in bundle.SITES:
        assert len(pattern.findall(text)) == 1, f"ambiguous anchor: {description}"


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------


def test_apply_patch_injects_helper_and_call_sites(fake_bundle: Path):
    changed, message = bundle.apply_patch(fake_bundle, MODEL)

    assert changed is True
    assert message == "patched"

    text = fake_bundle.read_text(encoding="utf-8")
    assert "function hpyMapModel(incoming)" in text
    assert f'return "{MODEL}";' in text
    assert "hpyMapModel(options.modelMode)" in text
    assert "hpyMapModel(options.model)" in text
    assert "hpyMapModel(message.meta.model)" in text


def test_apply_patch_records_the_model_in_the_marker(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, MODEL)

    text = fake_bundle.read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) == MODEL


def test_apply_patch_creates_a_backup(fake_bundle: Path):
    backup = fake_bundle.with_suffix(fake_bundle.suffix + ".hpy-backup")
    assert not backup.exists()

    bundle.apply_patch(fake_bundle, MODEL)

    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == FAKE_BUNDLE


def test_apply_patch_does_not_overwrite_an_existing_backup(fake_bundle: Path):
    backup = fake_bundle.with_suffix(fake_bundle.suffix + ".hpy-backup")
    bundle.apply_patch(fake_bundle, MODEL)
    original_backup = backup.read_text(encoding="utf-8")

    # Change the model - the backup must still hold the pristine original.
    bundle.apply_patch(fake_bundle, "another-model")

    assert backup.read_text(encoding="utf-8") == original_backup


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_apply_patch_is_idempotent(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, MODEL)
    after_first = fake_bundle.read_text(encoding="utf-8")

    changed, message = bundle.apply_patch(fake_bundle, MODEL)

    assert changed is False
    assert message == "already patched"
    assert fake_bundle.read_text(encoding="utf-8") == after_first


def test_helper_is_not_duplicated_on_reapply(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, MODEL)
    bundle.apply_patch(fake_bundle, MODEL)

    text = fake_bundle.read_text(encoding="utf-8")
    assert text.count("function hpyMapModel") == 1


# --------------------------------------------------------------------------
# Re-targeting
# --------------------------------------------------------------------------


def test_changing_the_model_retargets_cleanly(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, "old-model")
    bundle.apply_patch(fake_bundle, "new-model")

    text = fake_bundle.read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) == "new-model"
    assert "old-model" not in text
    assert text.count("function hpyMapModel") == 1


# --------------------------------------------------------------------------
# Reverting
# --------------------------------------------------------------------------


def test_strip_patch_restores_the_original_text(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, MODEL)
    patched = fake_bundle.read_text(encoding="utf-8")

    assert bundle.strip_patch(patched).rstrip("\n") == FAKE_BUNDLE.rstrip("\n")


def test_unpatch_restores_from_backup(fake_bundle: Path, monkeypatch):
    bundle.apply_patch(fake_bundle, MODEL)
    monkeypatch.setattr(bundle, "BUNDLE_DIR", fake_bundle.parent)

    restored = bundle.unpatch()

    assert restored == 1
    assert fake_bundle.read_text(encoding="utf-8") == FAKE_BUNDLE


def test_unpatch_is_a_noop_without_a_backup(fake_bundle: Path, monkeypatch):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", fake_bundle.parent)

    assert bundle.unpatch() == 0
    assert fake_bundle.read_text(encoding="utf-8") == FAKE_BUNDLE


# --------------------------------------------------------------------------
# Refusing to write a partial patch
# --------------------------------------------------------------------------


def test_partial_match_is_refused_and_file_untouched(tmp_path: Path):
    # Two of three anchors present - a shape we do not recognise.
    partial = (
        FAKE_BUNDLE
        .replace(
            "if (options?.model) {\n          launch.args.push(\"--model\", options.model);\n        }\n",
            "",
        )
        .replace("message.meta.model || void 0", "message.meta.model")
    )
    path = tmp_path / "index-partial.mjs"
    path.write_text(partial, encoding="utf-8")

    changed, message = bundle.apply_patch(path, MODEL)

    assert changed is False
    assert message.startswith("PARTIAL")
    assert path.read_text(encoding="utf-8") == partial
    assert not path.with_suffix(path.suffix + ".hpy-backup").exists()


def test_bundle_without_any_anchor_is_skipped(tmp_path: Path):
    path = tmp_path / "index-noplumbing.mjs"
    path.write_text("export const nothing = 1;\n", encoding="utf-8")

    changed, message = bundle.apply_patch(path, MODEL)

    assert changed is False
    assert message == "no anchors (skipped)"
    assert not path.with_suffix(path.suffix + ".hpy-backup").exists()


# --------------------------------------------------------------------------
# Model-name quoting
# --------------------------------------------------------------------------


def test_model_names_are_quoted_safely(fake_bundle: Path):
    tricky = 'we"ird\\model'
    bundle.apply_patch(fake_bundle, tricky)

    text = fake_bundle.read_text(encoding="utf-8")
    assert bundle.read_applied_model(text) == tricky

    literal = re.search(r"if \(incoming === (\"(?:[^\"\\]|\\.)*\")\)", text)
    assert literal is not None
    assert literal.group(1) == '"we\\"ird\\\\model"'


def test_colon_and_brackets_survive_quoting(fake_bundle: Path):
    bundle.apply_patch(fake_bundle, MODEL)

    text = fake_bundle.read_text(encoding="utf-8")
    assert f'if (incoming === "{MODEL}")' in text


# --------------------------------------------------------------------------
# ensure_patched / status across multiple bundles
# --------------------------------------------------------------------------


def test_ensure_patched_handles_mixed_bundles(tmp_path: Path, monkeypatch):
    real = tmp_path / "index-real.mjs"
    real.write_text(FAKE_BUNDLE, encoding="utf-8")
    other = tmp_path / "index-other.mjs"
    other.write_text("export const x = 1;\n", encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    assert bundle.ensure_patched(MODEL) is True

    assert bundle.read_applied_model(real.read_text(encoding="utf-8")) == MODEL
    assert other.read_text(encoding="utf-8") == "export const x = 1;\n"


def test_ensure_patched_without_a_model_is_a_noop(tmp_path: Path, monkeypatch):
    real = tmp_path / "index-real.mjs"
    real.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    assert bundle.ensure_patched("") is True
    assert real.read_text(encoding="utf-8") == FAKE_BUNDLE


def test_ensure_patched_reports_failure_when_no_bundles(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path / "missing")

    assert bundle.ensure_patched(MODEL) is False


def test_status_lists_each_bundle(tmp_path: Path, monkeypatch):
    patched = tmp_path / "index-a.mjs"
    patched.write_text(FAKE_BUNDLE, encoding="utf-8")
    bundle.apply_patch(patched, MODEL)
    clean = tmp_path / "index-b.mjs"
    clean.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    result = dict(bundle.status())

    assert result["index-a.mjs"] == MODEL
    assert result["index-b.mjs"] is None


# --------------------------------------------------------------------------
# Bundle discovery
# --------------------------------------------------------------------------


def test_find_bundles_returns_empty_for_missing_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path / "gone")

    assert bundle.find_bundles() == []


def test_find_bundles_ignores_non_index_files(tmp_path: Path, monkeypatch):
    (tmp_path / "index-a.mjs").write_text("x", encoding="utf-8")
    (tmp_path / "cli.mjs").write_text("x", encoding="utf-8")
    (tmp_path / "index.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    names = [p.name for p in bundle.find_bundles()]

    assert names == ["index-a.mjs"]


def test_bundle_dir_prefers_npm_global_root(tmp_path: Path, monkeypatch):
    """The npm global root wins when it holds a happy install."""
    npm_root = tmp_path / "npmroot"
    dist = npm_root / "happy" / "dist"
    dist.mkdir(parents=True)

    class Result:
        stdout = str(npm_root)

    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: Result())

    assert bundle._bundle_dir() == dist


def test_bundle_dir_falls_back_when_npm_root_has_no_happy(tmp_path: Path, monkeypatch):
    """An npm root without a happy install falls through to the OS default."""
    npm_root = tmp_path / "npmroot"
    npm_root.mkdir()

    class Result:
        stdout = str(npm_root)

    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(bundle.sys, "platform", "win32")

    expected = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "happy" / "dist"
    assert bundle._bundle_dir() == expected


def test_bundle_dir_survives_npm_failure(tmp_path: Path, monkeypatch):
    """A missing or broken npm binary must not crash the patcher."""

    def boom(*args, **kwargs):
        raise OSError("npm not found")

    monkeypatch.setattr(bundle.subprocess, "run", boom)
    monkeypatch.setattr(bundle.sys, "platform", "win32")

    expected = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "happy" / "dist"
    assert bundle._bundle_dir() == expected


def test_bundle_dir_on_posix(monkeypatch):
    class Result:
        stdout = ""

    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(bundle.sys, "platform", "linux")

    assert bundle._bundle_dir() == Path("/usr/local/lib/node_modules/happy/dist")


# --------------------------------------------------------------------------
# ensure_patched - verbose and error paths
# --------------------------------------------------------------------------


def test_ensure_patched_verbose_reports_missing_bundles(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path / "gone")

    assert bundle.ensure_patched(MODEL, verbose=True) is False
    assert "no bundle found" in capsys.readouterr().err


def test_ensure_patched_verbose_reports_missing_model(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    assert bundle.ensure_patched("", verbose=True) is True
    assert "no model configured" in capsys.readouterr().err


def test_ensure_patched_survives_an_unwritable_bundle(tmp_path: Path, monkeypatch, capsys):
    """One unreadable bundle must not abort patching the others."""
    good = tmp_path / "index-good.mjs"
    good.write_text(FAKE_BUNDLE, encoding="utf-8")
    bad = tmp_path / "index-bad.mjs"
    bad.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    real_read = Path.read_text

    def flaky_read(self, *args, **kwargs):
        if self.name == "index-bad.mjs":
            raise OSError("permission denied")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read)

    assert bundle.ensure_patched(MODEL) is False
    assert "cannot patch index-bad.mjs" in capsys.readouterr().err
    # The healthy bundle was still patched.
    assert bundle.read_applied_model(real_read(good, encoding="utf-8")) == MODEL


def test_ensure_patched_verbose_names_each_bundle(tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / "index-abc.mjs"
    target.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)

    bundle.ensure_patched(MODEL, verbose=True)

    assert "index-abc.mjs: applied" in capsys.readouterr().err


def test_ensure_patched_verbose_silent_when_already_applied(tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / "index-abc.mjs"
    target.write_text(FAKE_BUNDLE, encoding="utf-8")
    bundle.apply_patch(target, MODEL)
    monkeypatch.setattr(bundle, "BUNDLE_DIR", tmp_path)
    capsys.readouterr()

    bundle.ensure_patched(MODEL, verbose=True)

    assert "already patched" in capsys.readouterr().err
