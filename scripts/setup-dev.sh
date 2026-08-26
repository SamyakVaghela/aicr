#!/usr/bin/env bash
#
# One-command setup for a developer's machine.
#
#   ./scripts/setup-dev.sh                  # install aicr, then hook into cwd repo
#   ./scripts/setup-dev.sh ~/work/api       # install aicr, then hook into that repo
#
set -euo pipefail

AICR_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_REPO="${1:-$(pwd)}"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!  \033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗  \033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is not installed."

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.9+ is required but was not found."
say "Using $($PY --version)"

# --- install the tool -------------------------------------------------------
if command -v pipx >/dev/null 2>&1; then
  say "Installing aicr with pipx"
  pipx install --force "$AICR_SRC"
  AICR_BIN="$(command -v aicr || echo "$HOME/.local/bin/aicr")"
else
  warn "pipx not found — installing into a dedicated venv at ~/.aicr-venv"
  "$PY" -m venv "$HOME/.aicr-venv"
  "$HOME/.aicr-venv/bin/pip" install --quiet --upgrade pip
  "$HOME/.aicr-venv/bin/pip" install --quiet "$AICR_SRC"
  AICR_BIN="$HOME/.aicr-venv/bin/aicr"
  mkdir -p "$HOME/.local/bin"
  ln -sf "$AICR_BIN" "$HOME/.local/bin/aicr"
  say "Linked $HOME/.local/bin/aicr"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) warn "Add this to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
fi

say "Installed: $("$AICR_BIN" --version)"

# --- API key ----------------------------------------------------------------
PROVIDER="$(grep -E '^\s*provider\s*=' "$TARGET_REPO/.aicr.toml" 2>/dev/null \
            | head -1 | sed -E 's/.*"(.*)".*/\1/' || true)"
PROVIDER="${PROVIDER:-anthropic}"

case "$PROVIDER" in
  anthropic)
    [ -n "${ANTHROPIC_API_KEY:-}" ] || warn "ANTHROPIC_API_KEY is not set. Add to your shell profile:
       export ANTHROPIC_API_KEY=sk-ant-..." ;;
  openai)
    [ -n "${OPENAI_API_KEY:-}" ] || warn "OPENAI_API_KEY is not set. Add to your shell profile:
       export OPENAI_API_KEY=sk-..." ;;
  gemini|google)
    if [ -z "${GEMINI_API_KEY:-}" ]; then
      warn "GEMINI_API_KEY is not set. Get one at https://aistudio.google.com/apikey then:
       export GEMINI_API_KEY=..."
    fi
    warn "Gemini: make sure billing is enabled on the key. On the FREE tier Google
       uses your prompts (your source code) to improve their products." ;;
  ollama)
    command -v ollama >/dev/null 2>&1 || warn "ollama is not installed: https://ollama.com/download" ;;
esac

# --- hook -------------------------------------------------------------------
if git -C "$TARGET_REPO" rev-parse --git-dir >/dev/null 2>&1; then
  say "Installing pre-push hook in $TARGET_REPO"
  "$AICR_BIN" install-hook --repo "$TARGET_REPO" || \
    warn "Hook not installed. If another pre-push hook exists, rerun with:
       aicr install-hook --repo \"$TARGET_REPO\" --force"
  say "Running doctor"
  "$AICR_BIN" doctor --repo "$TARGET_REPO" || true
else
  warn "$TARGET_REPO is not a git repository — skipped hook install."
  say "Later, from inside your repo, run:  aicr install-hook"
fi

say "Done. Every 'git push' from that repo now runs the AI review first."
