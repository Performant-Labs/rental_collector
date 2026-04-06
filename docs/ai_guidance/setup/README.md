# AI Guidance Subtree Setup

When `ai_guidance` is consumed as a **git subtree** inside another project, these scripts let you `ai:pull` and `ai:push` changes without remembering the full `git subtree` invocations.

## What You Get

| Command | What it does |
|---------|-------------|
| `ai:pull` | Pulls the latest from `Performant-Labs/ai_guidance` into `docs/ai_guidance/` (squash merge) |
| `ai:push` | Pushes local changes back upstream |
| `ai:pull --model opus` | Uses a specific Claude model for the change summary |

Both commands:
- Check for a clean working tree before proceeding
- Ask Claude CLI for advice if the tree is dirty (optional — requires [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli))
- `ai:pull` summarizes what changed using Claude after a successful pull

## Prerequisites

| Tool | Required | Install |
|------|----------|---------|
| **git** | ✅ | Xcode CLT or [git-scm.com](https://git-scm.com/) |
| **uv** | ✅ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Claude CLI** | Optional | `npm install -g @anthropic-ai/claude-code` then run `claude` and `/login` |

## Quick Install

From the **root of your project** (the repo that contains `ai_guidance` as a subtree):

```bash
./setup/install.sh
```

The script will:

1. **Verify** that `uv` and `git` are installed
2. **Copy** the Python scripts to `~/LocalDevelopment/python_scripts/`
3. **Add** `ai:pull` and `ai:push` aliases to your `~/.zshrc` (or `~/.bashrc`)

Use `--force` to skip confirmation prompts:

```bash
./setup/install.sh --force
```

After installation, reload your shell:

```bash
source ~/.zshrc   # or open a new terminal
```

## Manual Install

If you prefer to set things up by hand:

### 1. Copy the scripts

```bash
mkdir -p ~/LocalDevelopment/python_scripts
cp setup/scripts/ai_common.py ~/LocalDevelopment/python_scripts/
cp setup/scripts/ai_pull.py   ~/LocalDevelopment/python_scripts/
cp setup/scripts/ai_push.py   ~/LocalDevelopment/python_scripts/
```

### 2. Add aliases to your shell

Append this to `~/.zshrc` (or `~/.bashrc`):

```bash
# --- AI Subtree Aliases (ai_guidance) ---
_ai_pull() {
  uv run ~/LocalDevelopment/python_scripts/ai_pull.py "$@"
}
_ai_push() {
  uv run ~/LocalDevelopment/python_scripts/ai_push.py "$@"
}

alias ai:pull="_ai_pull"
alias ai:push="_ai_push"
# --- End AI Subtree Aliases ---
```

### 3. Reload

```bash
source ~/.zshrc
```

## File Overview

```
setup/
├── README.md          ← this file
├── install.sh         ← automated installer
└── scripts/
    ├── ai_common.py   ← shared config & helpers
    ├── ai_pull.py     ← ai:pull implementation
    └── ai_push.py     ← ai:push implementation
```

## Configuration

The subtree prefix, remote URL, and branch are defined in `scripts/ai_common.py`:

```python
PREFIX = "docs/ai_guidance"
REMOTE = "git@github.com:Performant-Labs/ai_guidance.git"
BRANCH = "main"
```

If your project mounts `ai_guidance` at a different path, update `PREFIX` accordingly.

## Customizing the Claude Model

You can specify which Claude model to use in three ways (highest priority first):

1. **CLI flag**: `ai:pull --model claude-opus-4-5`
2. **Environment variable**: `export AI_SYNC_MODEL=opus`
3. **Default**: Claude CLI's default model
