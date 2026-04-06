#!/usr/bin/env bash
#
# install.sh — Set up ai:pull and ai:push aliases for the ai_guidance subtree.
#
# This script:
#   1. Verifies prerequisites (uv, git)
#   2. Copies the Python scripts to ~/LocalDevelopment/python_scripts/
#   3. Appends shell aliases to ~/.zshrc (or ~/.bashrc)
#
# Usage:
#   ./setup/install.sh            # interactive, asks before writing
#   ./setup/install.sh --force    # skip confirmation prompts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_SRC="$SCRIPT_DIR/scripts"
INSTALL_DIR="$HOME/LocalDevelopment/python_scripts"
FORCE=false

[[ "${1:-}" == "--force" ]] && FORCE=true

# ─── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${CYAN}▸${RESET} $*"; }
ok()    { echo -e "${GREEN}✔${RESET} $*"; }
fail()  { echo -e "${RED}✖${RESET} $*"; exit 1; }
dim()   { echo -e "${DIM}$*${RESET}"; }

confirm() {
    if $FORCE; then return 0; fi
    read -rp "  $1 [Y/n] " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

# ─── Prerequisites ───────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${CYAN}◆ ai_guidance subtree setup${RESET}"
echo

info "Checking prerequisites…"

if ! command -v uv &>/dev/null; then
    fail "'uv' is not installed. Install it first: https://docs.astral.sh/uv/getting-started/installation/"
fi
ok "uv found: $(uv --version)"

if ! command -v git &>/dev/null; then
    fail "'git' is not installed."
fi
ok "git found: $(git --version)"

# Optional: check for Claude CLI
if command -v claude &>/dev/null; then
    ok "claude CLI found (enables AI-powered advice on errors)"
else
    dim "  claude CLI not found — AI advice will be unavailable (optional)"
fi

# ─── Install Python scripts ─────────────────────────────────────────────────
echo
info "Installing Python scripts → ${INSTALL_DIR}/"

mkdir -p "$INSTALL_DIR"

for script in ai_common.py ai_pull.py ai_push.py; do
    src="$SCRIPTS_SRC/$script"
    dst="$INSTALL_DIR/$script"

    if [[ -f "$dst" ]]; then
        if cmp -s "$src" "$dst"; then
            dim "  $script — already up to date"
            continue
        fi
        if ! confirm "$script already exists and differs. Overwrite?"; then
            dim "  Skipping $script"
            continue
        fi
    fi

    cp "$src" "$dst"
    ok "Installed $script"
done

# ─── Shell aliases ───────────────────────────────────────────────────────────
echo
info "Configuring shell aliases…"

# Detect shell config file
if [[ -n "${ZSH_VERSION:-}" || "$SHELL" == */zsh ]]; then
    RC_FILE="$HOME/.zshrc"
else
    RC_FILE="$HOME/.bashrc"
fi

ALIAS_BLOCK='# --- AI Subtree Aliases (ai_guidance) ---
_ai_pull() {
  uv run ~/LocalDevelopment/python_scripts/ai_pull.py "$@"
}
_ai_push() {
  uv run ~/LocalDevelopment/python_scripts/ai_push.py "$@"
}

alias ai:pull="_ai_pull"
alias ai:push="_ai_push"
# --- End AI Subtree Aliases ---'

if grep -q "alias ai:pull" "$RC_FILE" 2>/dev/null; then
    ok "Aliases already present in $RC_FILE"
else
    if confirm "Add ai:pull / ai:push aliases to $RC_FILE?"; then
        echo "" >> "$RC_FILE"
        echo "$ALIAS_BLOCK" >> "$RC_FILE"
        ok "Aliases added to $RC_FILE"
    else
        echo
        dim "Skipped. To add manually, append this to $RC_FILE:"
        echo
        echo "$ALIAS_BLOCK"
    fi
fi

# ─── Done ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${GREEN}✔ Setup complete.${RESET}"
echo
dim "Run 'source $RC_FILE' or open a new terminal, then:"
echo
echo "  ai:pull          # pull latest ai_guidance from upstream"
echo "  ai:push          # push local changes to upstream"
echo "  ai:pull --model opus  # use a specific Claude model"
echo
