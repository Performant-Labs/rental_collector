import os
import subprocess

from rich.console import Console
from rich.panel import Panel

console = Console()

PREFIX = "docs/ai_guidance"
REMOTE = "git@github.com:Performant-Labs/ai_guidance.git"
BRANCH = "main"


def run(cmd, live_output=False):
    if live_output:
        result = subprocess.run(cmd, shell=True)
    else:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result


def ask_claude(prompt, model=None):
    # Model priority: CLI arg > AI_SYNC_MODEL env var > claude default
    model = model or os.environ.get("AI_SYNC_MODEL")
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    if "Not logged in" in result.stdout:
        console.print("\n[yellow]⚠ Claude CLI is not logged in. Run [bold]claude[/bold] in your terminal and complete [bold]/login[/bold] to enable AI advice.[/yellow]")
    return None


def print_header(operation, model=None):
    console.print(f"\n[bold cyan]◆ ai:{operation}[/bold cyan]")
    console.print(f"  [dim]Subtree :[/dim] {PREFIX}")
    console.print(f"  [dim]Remote  :[/dim] {REMOTE}")
    console.print(f"  [dim]Branch  :[/dim] {BRANCH}")
    if model:
        console.print(f"  [dim]Model   :[/dim] {model}")
    console.print()


def check_dirty_tree(operation, model=None):
    """Returns True if tree is clean, False (and prints advice) if dirty."""
    dirty = (
        run("git diff --quiet").returncode != 0 or
        run("git diff --cached --quiet").returncode != 0
    )
    if not dirty:
        return True

    status = run("git status --short").stdout.strip()
    console.print("[bold red]✖ Cannot proceed — working tree is dirty.[/bold red]")
    console.print("  Resolve these files first:\n")
    for line in status.splitlines():
        console.print(f"    [yellow]{line}[/yellow]")

    console.print("\n[dim]Asking Claude for advice…[/dim]")
    advice = ask_claude(
        f"I'm trying to {operation} a remote git subtree but my working tree is dirty. "
        f"Here is the output of git status --short:\n\n{status}\n\n"
        f"Give me bullet points (not prose) with specific git commands to resolve this so I can proceed.",
        model=model,
    )
    if advice:
        console.print(Panel(advice, title="[bold]Claude's advice[/bold]", border_style="yellow"))

    console.print()
    return False


def parse_args(description):
    import argparse
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", default=None, help="Claude model to use (e.g. sonnet, opus, claude-opus-4-5)")
    return parser.parse_args()
