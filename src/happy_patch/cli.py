"""Command-line entry points for happy-patch.

Two commands:

``hpy``    wrapper - forwards config, patches the bundle, then launches happy.
``happypatch``  patcher - apply / revert / inspect the bundle patch directly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import bundle
from .config import (
    SETTINGS_PATH,
    env_flag,
    find_happy,
    is_strict_subcommand,
    load_claude_env,
    resolve_model,
    run,
    warn,
)

VERBOSE = env_flag("HPY_VERBOSE")


def log(message: str) -> None:
    if VERBOSE:
        print(f"[hpy] {message}", file=sys.stderr)


def run_patcher(model: str) -> None:
    """Patch the installed happy bundle so client-sent names are rewritten."""
    if env_flag("HPY_NO_PATCH"):
        log("patching disabled (HPY_NO_PATCH)")
        return
    if not model:
        log("no model configured; skipping patch")
        return

    try:
        if not bundle.ensure_patched(model, verbose=VERBOSE):
            warn("patch incomplete - remote turns may use the wrong model")
    except Exception as exc:  # noqa: BLE001 - never block startup on a patch failure
        warn(f"patching failed: {exc}")


def hpy_main(argv: list[str] | None = None) -> int:
    """Entry point for the `hpy` wrapper."""
    argv = sys.argv[1:] if argv is None else argv

    env = load_claude_env(SETTINGS_PATH)
    model = resolve_model(env, SETTINGS_PATH)

    if VERBOSE:
        log(f"forwarding {len(env)} env vars")
        for key in sorted(env):
            hidden = "TOKEN" in key or "KEY" in key
            log(f"  {key}={'<redacted>' if hidden else env[key]}")
        log(f"model to force: {model or '(none)'}")

    run_patcher(model)

    happy = find_happy()
    if is_strict_subcommand(argv):
        log(f"subcommand {argv[0]!r}: config passed via environment only")
    return run(happy, argv, env)


def patch_main(argv: list[str] | None = None) -> int:
    """Entry point for the `happypatch` tool."""
    parser = argparse.ArgumentParser(
        prog="happypatch",
        description="Apply, inspect or revert happy's model-name patch.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--model", help="model name to force")
    group.add_argument("--status", action="store_true", help="show current patch state")
    group.add_argument("--unpatch", action="store_true", help="restore bundles from backup")
    group.add_argument("--path", action="store_true", help="print the bundle directory")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.path:
        print(bundle.BUNDLE_DIR)
        return 0

    if args.unpatch:
        print(f"restored {bundle.unpatch(verbose=True)} bundle(s)")
        return 0

    if args.status:
        found = False
        for name, model in bundle.status():
            found = True
            print(f"{name}: {model or 'not patched'}")
        if not found:
            print(f"no bundles found under {bundle.BUNDLE_DIR}")
        return 0

    ok = bundle.ensure_patched(args.model, verbose=True)
    return 0 if ok else 1
