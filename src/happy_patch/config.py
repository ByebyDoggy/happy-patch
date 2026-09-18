"""Reading Claude Code's configuration and launching happy with it."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Env vars worth forwarding into the Claude Code subprocess. An allowlist, so
# unrelated settings (PATH, HOME, ...) never leak through.
FORWARD_PREFIXES = ("ANTHROPIC_", "CLAUDE_")

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Subcommands parse their own arguments strictly and reject anything extra
# (`happy resume` throws on a second argument), so --claude-env cannot be
# injected alongside them. They still receive the config, via the exported
# environment: happy's session sanitizer only strips HAPPY_*/CODEX_* keys.
STRICT_SUBCOMMANDS = frozenset(
    {
        "auth",
        "resume",
        "codex",
        "gemini",
        "agy",
        "acp",
        "connect",
        "sandbox",
        "notify",
        "daemon",
        "doctor",
    }
)


def env_flag(name: str) -> bool:
    """Truthy check for an env var. '0', 'false', 'no', 'off' and unset are all false."""
    import os

    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no", "off")


def load_claude_env(settings_path: Path = SETTINGS_PATH) -> dict[str, str]:
    """Return the ANTHROPIC_*/CLAUDE_* entries from settings.json's env block."""
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        warn(f"{settings_path} not found, using ambient env")
        return {}
    except OSError as exc:
        warn(f"cannot read {settings_path}: {exc}")
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        warn(f"{settings_path} is not valid JSON: {exc}")
        return {}

    env = data.get("env")
    if not isinstance(env, dict):
        return {}

    return {
        k: str(v)
        for k, v in env.items()
        if isinstance(k, str) and k.startswith(FORWARD_PREFIXES) and v is not None
    }


def resolve_model(env: dict[str, str], settings_path: Path = SETTINGS_PATH) -> str:
    """Pick the model name to force. ANTHROPIC_MODEL wins; else settings.model."""
    if env.get("ANTHROPIC_MODEL"):
        return env["ANTHROPIC_MODEL"]

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    model = data.get("model")
    return str(model) if model else ""


def is_strict_subcommand(args: list[str]) -> bool:
    """True when the invocation routes to a subcommand that parses args strictly.

    happy dispatches on argv[0], so a leading ``claude`` (which happy strips)
    or a plain flag both mean "start a session" and can take --claude-env.
    """
    return bool(args) and args[0] in STRICT_SUBCOMMANDS


def find_happy() -> str:
    """Locate the happy executable, skipping our own shim."""
    self_path = Path(__file__).resolve()
    for name in ("happy.cmd", "happy.exe", "happy"):
        found = shutil.which(name)
        if found and Path(found).resolve() != self_path:
            return found
    warn("error: cannot find 'happy' on PATH")
    sys.exit(127)


def build_argv(happy: str, user_args: list[str], env: dict[str, str]) -> list[str]:
    """Assemble the happy command line.

    Argument order matters: happy only recognises subcommands and only strips
    the optional ``claude`` prefix when they sit in argv[0]. Injecting flags
    ahead of the user's would push both out of position, so user args come
    first and --claude-env follows.
    """
    argv = [happy] + user_args
    if not is_strict_subcommand(user_args):
        for key, value in env.items():
            argv += ["--claude-env", f"{key}={value}"]
    return argv


def build_child_env(env: dict[str, str]) -> dict[str, str]:
    """Ambient environment plus the forwarded config.

    The environment is what carries the config to strict subcommands, and it
    survives happy's session sanitizer, which only strips HAPPY_*/CODEX_*.
    """
    import os

    child = dict(os.environ)
    child.update(env)
    return child


def warn(message: str) -> None:
    print(f"[happy-patch] {message}", file=sys.stderr)


def run(happy: str, user_args: list[str], env: dict[str, str]) -> int:
    """Launch happy and return its exit code."""
    argv = build_argv(happy, user_args, env)
    child_env = build_child_env(env)
    try:
        return subprocess.call(argv, env=child_env)
    except KeyboardInterrupt:
        return 130
