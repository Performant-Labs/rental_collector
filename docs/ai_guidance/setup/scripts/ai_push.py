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
    args = parse_args("Push local changes to the remote ai_guidance subtree.")
    model = args.model

    print_header("push", model)

    if not check_dirty_tree("push local changes to", model):
        sys.exit(1)

    console.print("[dim]Pushing to remote…[/dim]\n")
    push = run(
        f"git subtree push --prefix={PREFIX} {REMOTE} {BRANCH}",
        live_output=True,
    )

    if push.returncode != 0:
        console.print("\n[bold red]✖ ai:push failed. Check the output above.[/bold red]\n")
        sys.exit(1)

    console.print(f"\n[bold green]✔ ai:push complete.[/bold green]\n")


if __name__ == "__main__":
    main()
