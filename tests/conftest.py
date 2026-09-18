"""Shared fixtures. Adds src/ to sys.path so tests run without installing."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# A miniature stand-in for the real happy bundle. It carries all three anchor
# sites in the same shapes happy ships them in, so a patch built from it is
# representative. Keep the wording in sync with happy_patch.bundle.SITES.
MINIMAL_BUNDLE = """\
function buildResumeLaunch(session, options = {}) {
    const launch = { args: [], cwd: "." };
    if (options?.model) {
          launch.args.push("--model", options.model);
        }
    return launch;
}
function spawnMode(options) {
    const args = [];
    if (options.modelMode && options.modelMode !== "default") {
    args.push("--model", options.modelMode);
  }
    return args;
}
function handleMessage(message, currentModel) {
    let messageModel = currentModel;
    if (message.meta?.hasOwnProperty("model")) {
      messageModel = message.meta.model || void 0;
    }
    return messageModel;
}
"""
