# happy-patch

Make the [happy](https://github.com/slopus/happy) CLI use **your** Claude model
instead of the names its app and web client hardcode.

## The problem

Happy's mobile app and web client ship a fixed Claude model list —
`claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`. Whatever you pick is
forwarded verbatim to Claude Code as `--model <name>`, which **overrides both
`ANTHROPIC_MODEL` and the `model` field in `~/.claude/settings.json`**.

If Claude Code points at a third-party relay that uses different names (say
`cn:deepseek-v4.1-flash[1M]`), every remote turn dies with an
unrecognized-model error. The app's "Custom model" field doesn't help either —
it's gated to Codex only.

Upstream report: [slopus/happy#1721](https://github.com/slopus/happy/issues/1721).

## Why patching the CLI works

Every client funnels through the same chokepoint:

```
official app ──┐
               ├──→ Happy server ──→ happy CLI ──→ claude --model <name>
self-hosted web┘                          ↑
                                     patch here
```

Rewrite the name at the CLI and both clients are covered at once.

## Install

```sh
pip install -e .
```

This puts two commands on your PATH:

| Command | Purpose |
|---|---|
| `hpy` | Wrapper — reads your config, patches, launches happy |
| `happypatch` | Manage the patch directly |

## Usage

Run your session through the wrapper:

```sh
hpy                     # normal session
hpy --yolo              # any happy flag works
hpy claude --resume <uuid>   # resume a Claude Code session
hpy resume <happy-id>        # resume a Happy session
```

The wrapper reads `ANTHROPIC_*` / `CLAUDE_*` from `~/.claude/settings.json`,
so the model reaching your relay is always the one you configured locally.

### Managing the patch

```sh
happypatch --status                  # what is applied right now
happypatch --model "my-model[1m]"    # force a specific model
happypatch --unpatch                 # restore the original bundle
happypatch --path                    # where the bundle lives
```

### Environment

| Variable | Effect |
|---|---|
| `HPY_VERBOSE=1` | Show what is forwarded and patched |
| `HPY_NO_PATCH=1` | Skip patching for this run |

## How the patch works

Three model entry points are rewritten in happy's bundled JS — the ones for
new sessions, resumed sessions, and per-turn overrides from the client:

```js
function hpyMapModel(incoming) {
  if (!incoming) return incoming;
  if (incoming === "cn:deepseek-v4.1-flash[1M]") return incoming;
  return "cn:deepseek-v4.1-flash[1M]";
}
```

It is **idempotent and self-healing**:

- Already patched with the same model → no-op
- Model changed in `settings.json` → the old patch is reverted, a new one applied
- Bundle replaced by `npm i -g happy` → patched again on the next run
- Bundle shape changed (happy upgraded) → **refuses to write** and warns,
  rather than shipping a half-applied patch

Every patched bundle keeps a `.hpy-backup` of the original next to it.

## Argument handling

Two details in happy's CLI shape how the wrapper invokes it:

**Order matters.** happy dispatches on `argv[0]` and only strips the optional
`claude` prefix when it sits first. Injected flags must therefore come *after*
your arguments, never before.

**Subcommands reject extra flags.** `happy resume` throws on any second
argument, so `--claude-env` cannot accompany it. The wrapper detects this and
passes the config through the environment instead — which works because happy's
session sanitizer only strips `HAPPY_*`/`CODEX_*` keys, leaving `ANTHROPIC_*`
and `CLAUDE_*` intact.

## Not handled here

Server URL and TLS trust are yours to configure (`happy auth`,
`~/.happy/settings.json`). The wrapper deliberately leaves them alone so
re-pairing and upgrades stay predictable.

## Development

```sh
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -e ".[dev]"
pytest --cov=src/happy_patch
```

## License

MIT
