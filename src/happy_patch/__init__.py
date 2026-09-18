"""Idempotent patching of the happy CLI bundle's model handling.

The Happy mobile app and web client hardcode their Claude model list to names
like ``claude-fable-5`` / ``claude-opus-5`` / ``claude-sonnet-5`` (see
slopus/happy#1721). Those names are forwarded verbatim to Claude Code as
``--model <name>``, overriding both ``ANTHROPIC_MODEL`` and the ``model`` field
in ``~/.claude/settings.json``.

When Claude Code points at a third-party relay that uses different model names
(for example ``cn:deepseek-v4.1-flash[1M]``), every remote turn fails with an
unrecognized-model error.

The CLI is the right place to patch because every client funnels through it::

    app / web  ->  Happy server  ->  happy CLI  ->  ``claude --model <name>``

Patching is marker-guarded: it is a no-op when already applied, re-applied when
the target model changes, and automatically reinstated after
``npm i -g happy`` replaces the bundle.
"""

from .bundle import (
    BUNDLE_DIR,
    SITES,
    apply_patch,
    ensure_patched,
    find_bundles,
    read_applied_model,
    strip_patch,
    unpatch,
)

__version__ = "0.1.0"

__all__ = [
    "BUNDLE_DIR",
    "SITES",
    "apply_patch",
    "ensure_patched",
    "find_bundles",
    "read_applied_model",
    "strip_patch",
    "unpatch",
    "__version__",
]
