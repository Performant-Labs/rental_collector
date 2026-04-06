# /// script
# dependencies = ["rich"]
# ///

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from ai_common import (
    run, ask_claude, console, Panel,
    PREFIX, REMOTE, BRANCH,
    print_header, check_dirty_tree, parse_args,
)


def main():
    args = parse_args("Pull updates from the remote ai_guidance subtree.")
    model = args.model

    print_header("pull", model)

    if not check_dirty_tree("pull updates from", model):
        sys.exit(1)

    head_before = run("git rev-parse HEAD").stdout.strip()

    console.print("[dim]Pulling from remote…[/dim]\n")
    pull = run(
        f"git subtree pull --prefix={PREFIX} {REMOTE} {BRANCH} --squash",
        live_output=True,
    )

    if pull.returncode != 0:
        console.print("\n[bold red]✖ ai:pull failed. Check the output above.[/bold red]\n")
        sys.exit(1)

    console.print(f"\n[bold green]✔ ai:pull complete.[/bold green]")

    head_after = run("git rev-parse HEAD").stdout.strip()
    if head_before == head_after:
        console.print("[dim]Already up to date — nothing changed.[/dim]\n")
        return

    diff = run(f"git diff {head_before} HEAD -- {PREFIX}").stdout.strip()
    if diff:
        console.print("\n[dim]Summarizing changes…[/dim]")
        summary = ask_claude(
            f"Summarize the following git diff for the '{PREFIX}' directory in 2-3 plain English sentences. "
            f"Focus on what actually changed conceptually, not file names or line counts.\n\n{diff[:3000]}",
            model=model,
        )
        if summary:
            console.print(Panel(summary, title="[bold]What changed[/bold]", border_style="cyan"))

    console.print()


if __name__ == "__main__":
    main()
