"""VibeCoder CLI — CADEN's coding assistant.

Mode 1: Standalone CLI — type 'vibe' in any terminal.
Mode 2: Server mode — serves WebSocket API for CADEN's GUI.

This CLI is CADEN-aware: it learns from past mistakes, uses past projects
for context, and records all model outputs for distillation.
"""

import os
import sys
from rich.console import Console


def print_help(console):
    console.print("[bold magenta]╭───────────────[ /commands ]───────────────╮[/bold magenta]")
    console.print("[bold cyan]  /help[/bold cyan]           [dim]Show this help[/dim]")
    console.print("[bold cyan]  /clear[/bold cyan]          [dim]Clear conversation history[/dim]")
    console.print("[bold cyan]  /model[/bold cyan]          [dim]Show or change the LLM model[/dim]")
    console.print("[bold cyan]  /lessons[/bold cyan]        [dim]Show learned lessons stats[/dim]")
    console.print("[bold cyan]  /distill[/bold cyan]        [dim]Show distillation progress[/dim]")
    console.print("[bold cyan]  /bandit[/bold cyan]         [dim]Show adaptive workflow stats[/dim]")
    console.print("[bold cyan]  /create-skill[/bold cyan]   [dim]Create a new skill interactively[/dim]")
    console.print("[bold cyan]  /list-skills[/bold cyan]    [dim]List registered skills[/dim]")
    console.print("[bold magenta]╰──────────────────────────────────────────╯[/bold magenta]")


def handle_command(cmd, console, agent_state):
    from agent import skill_create, skill_list, skill_invoke, working_memory

    if cmd == "/help":
        print_help(console)
    elif cmd == "/clear":
        working_memory["chat_history"].clear()
        working_memory["files_in_scope"].clear()
        working_memory["current_task"] = None
        working_memory["current_plan"] = None
        agent_state.clear()
        console.print("[bold green]Context cleared.[/bold green]")
    elif cmd == "/model":
        from model import get_active_model
        console.print(f"[bold yellow]Active:[/bold yellow] [bold cyan]{get_active_model()}[/bold cyan]")
        console.print("[dim]  Providers: Groq (primary), GitHub Models (fallback)[/dim]")
    elif cmd == "/lessons":
        from caden_bridge import lesson_count
        from memory import episode_count
        n_lessons = lesson_count()
        n_episodes = episode_count()
        console.print(f"[bold magenta]Learning stats[/bold magenta]")
        console.print(f"  Episodes stored:  [bold cyan]{n_episodes}[/bold cyan]")
        console.print(f"  Lessons learned:  [bold cyan]{n_lessons}[/bold cyan]")
    elif cmd == "/distill":
        from distill import distill_stats
        stats = distill_stats()
        if not stats:
            console.print("[dim]No distillation data yet — use the agent to start collecting.[/dim]")
        else:
            console.print("[bold magenta]Distillation progress[/bold magenta]")
            for ex_type, count in sorted(stats.items()):
                console.print(f"  {ex_type:<28} {count}")
    elif cmd == "/bandit":
        from bandit import arm_stats
        from memory import episode_count
        stats = arm_stats()
        total = episode_count()
        console.print(f"[bold magenta]Bandit arm stats[/bold magenta] [dim]({total} episodes stored)[/dim]")
        if not stats:
            console.print("  [dim](no data yet — run some tasks first)[/dim]")
        for cat, arms in sorted(stats.items()):
            console.print(f"  [bold cyan]{cat}[/bold cyan]")
            for arm in sorted(arms, key=lambda a: a['win_rate'], reverse=True):
                bar = '\u2588' * int(arm['win_rate'] * 20)
                console.print(
                    f"    {arm['variant']:<22} "
                    f"win={arm['win_rate']:.2f} "
                    f"[dim]α={arm['alpha']} β={arm['beta']}[/dim] "
                    f"[green]{bar}[/green]"
                )
    elif cmd == "/create-skill":
        skill_create()
    elif cmd == "/list-skills":
        skill_list()
    elif cmd.startswith("/invoke-skill"):
        parts = cmd.split()
        if len(parts) < 2:
            console.print("[bold red]Usage: /invoke-skill <name> [args][/bold red]")
            return
        skill_invoke(parts[1], *parts[2:])
    else:
        console.print(f"[bold red]Unknown command:[/bold red] {cmd}  (type /help)")


def main(workspace=None):
    console = Console()

    from model import get_active_model
    from tools import set_workspace, get_workspace

    ws = workspace or os.getcwd()
    set_workspace(ws)

    model_name = get_active_model()
    console.print()
    console.print("[bold magenta]╭────────────────────────────────────────────────╮[/bold magenta]")
    console.print("[bold magenta]│[/bold magenta]   [bold white]CADEN VibeCoder[/bold white]  [dim]— coding with memory[/dim]       [bold magenta]│[/bold magenta]")
    console.print("[bold magenta]╰────────────────────────────────────────────────╯[/bold magenta]")
    console.print(f"[dim]  model: {model_name}[/dim]")
    console.print(f"[dim]  workspace: {get_workspace()}[/dim]")

    # Show learning stats
    try:
        from caden_bridge import lesson_count
        from memory import episode_count
        n_l = lesson_count()
        n_e = episode_count()
        if n_l > 0 or n_e > 0:
            console.print(f"[dim]  {n_e} episodes, {n_l} lessons learned[/dim]")
    except Exception:
        pass

    console.print(f"[dim]  type /help for commands[/dim]")
    console.print()

    agent_state = {}

    while True:
        try:
            try:
                user_input = console.input("[bold magenta]You:[/bold magenta] ").strip()
            except KeyboardInterrupt:
                console.print("\n[dim]Goodbye.[/dim]")
                break
            except EOFError:
                console.print("\n[dim]Goodbye.[/dim]")
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                console.print("[dim]Goodbye.[/dim]")
                break

            if user_input.startswith("/"):
                try:
                    handle_command(user_input, console, agent_state)
                except KeyboardInterrupt:
                    console.print("[bold yellow]\nCommand cancelled.[/bold yellow]")
                continue

            from agent import agent_converse
            agent_state["current_task"] = user_input
            try:
                agent_converse(user_input, console)
            except KeyboardInterrupt:
                console.print("[bold yellow]\nInterrupted. (Ctrl+C again or type 'exit' to quit)[/bold yellow]")
            console.print()

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


if __name__ == "__main__":
    main()
