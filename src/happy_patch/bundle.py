"""Locating, patching and reverting the happy CLI bundle."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Bundles that may contain the injection sites.
TARGET_GLOB = "index-*.mjs"

# Marker layout: /* HPY_PATCH:BEGIN | <model> */ ... /* HPY_PATCH:END */
MARKER_RE = re.compile(
    r"/\* HPY_PATCH:BEGIN \| (?P<model>[^*]*?) \*/\n.*?/\* HPY_PATCH:END \*/\n",
    re.DOTALL,
)

# Rewrites any incoming model name to the configured one. Falsy input passes
# through so "reset to default" semantics survive.
HELPER_TEMPLATE = """/* HPY_PATCH:BEGIN | {model} */
function hpyMapModel(incoming) {{
  if (!incoming) return incoming;
  if (incoming === {model_json}) return incoming;
  return {model_json};
}}
/* HPY_PATCH:END */
"""

# (description, regex, replacement) - one entry per model entry point.
#
#   daemon spawn  - `--model` for newly created sessions
#   session resume - `--model` when resuming an existing session
#   message loop  - per-turn model override sent from the client
#
# Each pattern captures the surrounding context so the injected call keeps the
# original truthiness checks intact.
SITES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "daemon spawn (--model for new sessions)",
        re.compile(
            r'(if \(options\.modelMode && options\.modelMode !== "default"\) \{\s*\n'
            r'\s*args\.push\("--model", )options\.modelMode(\);)'
        ),
        r"\1hpyMapModel(options.modelMode)\2",
    ),
    (
        "session resume (--model for resumed sessions)",
        re.compile(
            r"(if \(options\?\.model\) \{\s*\n"
            r'\s*launch\.args\.push\("--model", )options\.model(\);)'
        ),
        r"\1hpyMapModel(options.model)\2",
    ),
    (
        "remote message loop (per-turn model override)",
        re.compile(r"(messageModel = )message\.meta\.model( \|\| void 0;)"),
        r"\1hpyMapModel(message.meta.model)\2",
    ),
]


def _bundle_dir() -> Path:
    """Locate happy's dist directory.

    Prefers the npm global root so the patcher works on any platform, with
    per-OS fallbacks for environments where npm is unavailable.
    """
    try:
        root = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
        if root:
            candidate = Path(root) / "happy" / "dist"
            if candidate.is_dir():
                return candidate
    except (OSError, subprocess.SubprocessError):
        pass

    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "happy" / "dist"
    return Path("/usr/local/lib/node_modules/happy/dist")


BUNDLE_DIR = _bundle_dir()


def find_bundles() -> list[Path]:
    """Return every candidate bundle under the dist directory."""
    if not BUNDLE_DIR.is_dir():
        return []
    return sorted(p for p in BUNDLE_DIR.glob(TARGET_GLOB) if p.is_file())


def read_applied_model(text: str) -> str | None:
    """Return the model recorded in an existing marker, or None."""
    match = MARKER_RE.search(text)
    return match.group("model").strip() if match else None


def strip_patch(text: str) -> str:
    """Remove a previously applied helper block and revert the call sites."""
    text = MARKER_RE.sub("", text)
    text = text.replace("hpyMapModel(options.modelMode)", "options.modelMode")
    text = text.replace("hpyMapModel(options.model)", "options.model")
    text = text.replace("hpyMapModel(message.meta.model)", "message.meta.model")
    return text


def _quote(value: str) -> str:
    """Render a Python string as a double-quoted JS string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def apply_patch(path: Path, model: str, verbose: bool = False) -> tuple[bool, str]:
    """Patch one bundle.

    Returns ``(changed, message)``. The file is left untouched unless every
    anchor matched, so a partial patch can never be written.
    """
    original = path.read_text(encoding="utf-8")
    if read_applied_model(original) == model:
        return False, "already patched"

    text = strip_patch(original)

    # Function declarations hoist in ESM, so appending works regardless of
    # where the call sites sit in the file.
    text = text.rstrip("\n") + "\n" + HELPER_TEMPLATE.format(
        model=model, model_json=_quote(model)
    )

    missed: list[str] = []
    for description, pattern, replacement in SITES:
        text, count = pattern.subn(replacement, text, count=1)
        if count == 0:
            missed.append(description)
        elif verbose:
            print(f"    patched: {description}", file=sys.stderr)

    if len(missed) == len(SITES):
        # No anchors at all: this chunk carries none of the model plumbing.
        # Several index-* chunks ship side by side; only one has the sites.
        return False, "no anchors (skipped)"

    if missed:
        # Partial match means the bundle changed shape under us.
        return False, f"PARTIAL - anchor(s) missing: {', '.join(missed)}"

    backup = path.with_suffix(path.suffix + ".hpy-backup")
    if not backup.exists():
        shutil.copy2(path, backup)

    path.write_text(text, encoding="utf-8")
    return True, "patched"


def ensure_patched(model: str, verbose: bool = False) -> bool:
    """Patch every bundle that needs it. Returns True when all are patched."""
    if not model:
        if verbose:
            print("[happy-patch] no model configured; skipping patch", file=sys.stderr)
        return True

    bundles = find_bundles()
    if not bundles:
        if verbose:
            print(f"[happy-patch] no bundle found under {BUNDLE_DIR}", file=sys.stderr)
        return False

    ok = True
    for bundle in bundles:
        try:
            changed, msg = apply_patch(bundle, model, verbose=verbose)
        except OSError as exc:
            print(f"[happy-patch] cannot patch {bundle.name}: {exc}", file=sys.stderr)
            ok = False
            continue
        if verbose or changed:
            print(f"[happy-patch] {bundle.name}: {'applied' if changed else msg}", file=sys.stderr)
    return ok


def unpatch(verbose: bool = False) -> int:
    """Restore bundles from their backups. Returns how many were restored."""
    restored = 0
    for bundle in find_bundles():
        backup = bundle.with_suffix(bundle.suffix + ".hpy-backup")
        if backup.exists():
            shutil.copy2(backup, bundle)
            restored += 1
            if verbose:
                print(f"[happy-patch] restored {bundle.name}", file=sys.stderr)
    return restored


def status() -> Iterable[tuple[str, str | None]]:
    """Yield ``(bundle name, applied model or None)`` for each candidate."""
    for bundle in find_bundles():
        yield bundle.name, read_applied_model(bundle.read_text(encoding="utf-8"))
