# AI Guidance

This repository serves as a centralized "source of truth" constraint-system and runbook for AI developer agents. It dictates [Browser Constraints (Headless Priority)](browser/CONSTRAINTS.md), standard operating procedures, known troubleshooting solutions, and codebase rules that AIs must blindly adhere to before taking execution actions in our ecosystem.

## How it Integrates

This repository is distributed into host projects (like `opencloud-voting` or `AlmondTTS`) using **Git Subtrees**—not Git Submodules! 

This design choice ensures that:
1. External contributors do not have to perform clunky `--recursive` clones.
2. The rules exist physically and natively inside the host project (`docs/ai_guidance/TROUBLESHOOTING.md`), completely visible to AIs.
3. Local rule-edits discovered inside host projects can be flawlessly pushed back upstream to this central repository without managing symlinks.

## Synchronizing the AI Rules

If you modify `TROUBLESHOOTING.md` inside a host project and want to publish that discovery here—or if you want to pull the newest global rules from here down into your host project—you must use `git subtree`.

### Pulling the Latest Constraints (Syncing Down)
Run this inside your host project's root directory:
```bash
git subtree pull --prefix=docs/ai_guidance git@github.com:Performant-Labs/ai_guidance.git main --squash
```

### Publishing Local Discoveries (Syncing Up)
When your AI updates the rules locally and you want to lock them in globally for the rest of the team:
```bash
git subtree push --prefix=docs/ai_guidance git@github.com:Performant-Labs/ai_guidance.git main
```

*(Warning: Be incredibly careful to pull before you push to avoid complex subtree merge-conflict histories.)*

---

## The "One-Touch" Automation (Highly Recommended)

Memorizing the verbose `subtree` commands is painful. The host repository owner highly recommends placing these two aliases at the bottom of your `~/.zshrc` or `~/.bash_profile`. This allows you to completely forget the boilerplate git syntax and flawlessly maintain synchronization.

```bash
# --- AI Subtree Global Aliases ---
alias ai:sync="git subtree pull --prefix=docs/ai_guidance git@github.com:Performant-Labs/ai_guidance.git main --squash"
alias ai:push="git subtree push --prefix=docs/ai_guidance git@github.com:Performant-Labs/ai_guidance.git main"
```

Once installed natively on your machine, no matter what language stack the project is, you just type:
- **`ai:sync`** to instantly update the local project's rules.
- **`ai:push`** to instantly publish new rules to the central nervous system.
