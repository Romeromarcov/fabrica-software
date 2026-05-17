#!/usr/bin/env python3
"""
CLI de la Fábrica de Software.

Comandos:
  new-feature "Nombre" --repo <repo>   Inicia un nuevo feature (modo completo por defecto)
  new-feature "Nombre" --repo <repo> --lite   Inicia en modo lite (bugfixes sin DB/MCP)
  resume <feature-id>    Reanuda un pipeline pausado (Stop Protocol o Checkpoint)
  status <feature-id>    Muestra el estado actual del feature
  list                   Lista todos los features y su estado
  repos                  Lista los repositorios disponibles
"""
import argparse
import sys
import uuid
import json
from pathlib import Path
from datetime import datetime

# Asegurar que el directorio del orquestador esté en el path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich import print as rprint

console = Console()


def _get_app():
    """Importación lazy del grafo (evita cargar Anthropic en comandos de info)."""
    from graph import compile_graph
    return compile_graph()


def _thread_config(feature_id: str) -> dict:
    return {"configurable": {"thread_id": feature_id}}


# ── Comando: new-feature ──────────────────────────────────────────────────────

def cmd_new_feature(feature_name: str, lite: bool, repo_name: str) -> None:
    from state import initial_state
    from tools.file_tools import save_run_metadata
    from config import resolve_repo_path, list_repos

    # Validar repo
    available = [r["name"] for r in list_repos()]
    if repo_name not in available:
        console.print(f"[red]Repositorio '{repo_name}' no encontrado.[/red]")
        console.print(f"[dim]Disponibles: {', '.join(available) or 'ninguno'}[/dim]")
        sys.exit(1)

    repo_path = resolve_repo_path(repo_name)
    mode = "lite" if lite else "completo"
    feature_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{feature_name[:20].replace(' ', '_').lower()}"
    )
    # Soporte para UI — permite override del feature_id
    import os
    feature_id = os.environ.get("FEATURE_ID_OVERRIDE", feature_id)

    console.print(Panel(
        f"[bold green]Nueva Feature[/bold green]\n"
        f"Nombre: [cyan]{feature_name}[/cyan]\n"
        f"Repo: [magenta]{repo_name}[/magenta]\n"
        f"Modo: [yellow]{mode.upper()}[/yellow]\n"
        f"ID: [dim]{feature_id}[/dim]",
        title="🏭 Fábrica de Software"
    ))

    state = initial_state(feature_id, feature_name, mode, repo_name, repo_path)
    app = _get_app()
    config = _thread_config(feature_id)

    # Guardar metadata inicial
    save_run_metadata(feature_id, {
        "feature_id": feature_id,
        "feature_name": feature_name,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "mode": mode,
        "status": "iniciando",
    })

    console.print(f"\n[dim]Iniciando Agente 1 (Planificador)...[/dim]")

    try:
        for chunk in app.stream(state, config=config, stream_mode="updates"):
            node_name = list(chunk.keys())[0]
            node_output = chunk[node_name]

            if node_name == "__interrupt__":
                # El grafo se pausó en un nodo humano
                interrupt_data = node_output[0].value
                _handle_interrupt(app, config, interrupt_data, feature_id)
                return

            _print_node_progress(node_name, node_output)

    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline interrumpido. Usa 'resume' para continuar.[/yellow]")
        console.print(f"[dim]Feature ID: {feature_id}[/dim]")


def _handle_interrupt(app, config: dict, interrupt_data: dict, feature_id: str) -> None:
    """Maneja cualquier interrupción humana del pipeline."""
    tipo = interrupt_data.get("tipo", "unknown")

    if tipo == "stop_protocol":
        console.print(Panel(
            Markdown(interrupt_data.get("mensaje", "")),
            title="⛔ STOP PROTOCOL — Agente 1",
            border_style="red"
        ))
        console.print("\n[bold]Tu respuesta:[/bold] ", end="")
        respuesta = input().strip()

        # Reanudar el grafo con la respuesta del Founder
        for chunk in app.stream(
            {"founder_approval": respuesta == "Plan aprobado. Pasa a ejecución."},
            config=config,
            stream_mode="updates",
        ):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                _handle_interrupt(app, config, chunk[node_name][0].value, feature_id)
                return
            _print_node_progress(node_name, chunk[node_name])

    elif tipo == "checkpoint":
        checkpoint_id = interrupt_data.get("checkpoint", "?")
        console.print(Panel(
            interrupt_data.get("mensaje", ""),
            title=f"🔔 Checkpoint {checkpoint_id}",
            border_style="blue"
        ))
        console.print("[dim]Presiona Enter para continuar (o escribe PAUSA):[/dim] ", end="")
        respuesta = input().strip()

        aprobado = respuesta.upper() != "PAUSA"
        key = f"checkpoint_{checkpoint_id.lower()}_approved"

        for chunk in app.stream(
            {key: aprobado},
            config=config,
            stream_mode="updates",
        ):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                _handle_interrupt(app, config, chunk[node_name][0].value, feature_id)
                return
            _print_node_progress(node_name, chunk[node_name])

    elif tipo == "qa_escalation":
        console.print(Panel(
            interrupt_data.get("mensaje", ""),
            title="⚠️  QA Escalation",
            border_style="yellow"
        ))
        console.print("[bold]Tu decisión (REDISEÑAR / ACEPTAR / CANCELAR):[/bold] ", end="")
        respuesta = input().strip()
        # Tras qa_escalation el pipeline termina en pipeline_detenido
        # El Founder debe corregir manualmente y crear un nuevo run si elige REDISEÑAR
        console.print(f"\n[yellow]Decisión registrada: {respuesta}[/yellow]")
        console.print(f"[dim]Corre 'new-feature' con el mismo nombre para reiniciar.[/dim]")


def _print_node_progress(node_name: str, output: dict) -> None:
    agent = output.get("current_agent", node_name)
    labels = {
        "a1_planificador":  "📋 Agente 1 — Planificador",
        "a6_db":            "🗄️  Agente 6 — DB Architect",
        "a8_mcp":           "🔧 Agente 8 — MCP Toolsmith",
        "a7_revision_1":    "🔒 Agente 7 — SecOps Rev.1",
        "checkpoint_a":     "🔔 Checkpoint A",
        "a2_backend":       "⚙️  Agente 2 — Backend",
        "a3_frontend":      "🖥️  Agente 3 — Frontend",
        "a4_qa":            "🧪 Agente 4 — QA",
        "a7_revision_2":    "🔒 Agente 7 — SecOps Rev.2",
        "checkpoint_b":     "🔔 Checkpoint B",
        "a5_refactor_doc":  "✨ Agente 5 — Refactor+Doc",
        "a1_pr_final":      "📦 Agente 1 — PR Final",
        "pipeline_detenido":"🚫 Pipeline Detenido",
    }
    label = labels.get(agent, f"⚡ {agent}")

    errors = output.get("errors", [])
    costs = output.get("cost_entries", [])
    cost_str = f" [dim](${sum(e['cost_usd'] for e in costs):.4f})[/dim]" if costs else ""

    if errors:
        console.print(f"  {label} [red]✗[/red]{cost_str}")
        for e in errors:
            console.print(f"    [red]→ {e}[/red]")
    else:
        console.print(f"  {label} [green]✓[/green]{cost_str}")


# ── Comando: resume ───────────────────────────────────────────────────────────

def cmd_resume(feature_id: str) -> None:
    from tools.file_tools import read_run_metadata

    meta = read_run_metadata(feature_id)
    if not meta:
        console.print(f"[red]Feature ID no encontrado: {feature_id}[/red]")
        return

    console.print(Panel(
        f"Reanudando: [cyan]{meta.get('feature_name', feature_id)}[/cyan]\n"
        f"Estado anterior: [yellow]{meta.get('status', '?')}[/yellow]",
        title="🔄 Resumiendo Pipeline"
    ))

    app = _get_app()
    config = _thread_config(feature_id)

    # Continuar desde el último checkpoint guardado
    for chunk in app.stream(None, config=config, stream_mode="updates"):
        node_name = list(chunk.keys())[0]
        if node_name == "__interrupt__":
            _handle_interrupt(app, config, chunk[node_name][0].value, feature_id)
            return
        _print_node_progress(node_name, chunk[node_name])


# ── Comando: status ───────────────────────────────────────────────────────────

def cmd_status(feature_id: str) -> None:
    from tools.file_tools import read_run_metadata, RUNS_DIR

    meta = read_run_metadata(feature_id)
    if not meta:
        console.print(f"[red]Feature no encontrado: {feature_id}[/red]")
        return

    run_dir = RUNS_DIR / feature_id
    outputs = list(run_dir.glob("output_*.md")) if run_dir.exists() else []

    console.print(Panel(
        f"[bold]{meta.get('feature_name', feature_id)}[/bold]\n\n"
        f"Modo:    [yellow]{meta.get('mode', '?').upper()}[/yellow]\n"
        f"Estado:  [cyan]{meta.get('status', '?')}[/cyan]\n"
        f"Iniciado: {meta.get('started_at', '?')[:19]}\n"
        f"Costo total: [green]${meta.get('total_cost_usd', 0):.4f} USD[/green]\n\n"
        f"Outputs generados ({len(outputs)}):\n" +
        "\n".join(f"  • {p.name}" for p in sorted(outputs)),
        title=f"📊 Status — {feature_id}"
    ))


# ── Comando: repos ───────────────────────────────────────────────────────────

def cmd_repos() -> None:
    from config import list_repos
    repos = list_repos()
    if not repos:
        console.print("[dim]No se encontraron repositorios en WORKSPACES_ROOT.[/dim]")
        return
    table = Table(title="Repositorios disponibles")
    table.add_column("Nombre", style="cyan")
    table.add_column("Ruta", style="dim")
    for r in repos:
        table.add_row(r["name"], r["path"])
    console.print(table)


# ── Comando: list ─────────────────────────────────────────────────────────────

def cmd_list() -> None:
    from tools.file_tools import RUNS_DIR
    import json

    if not RUNS_DIR.exists() or not any(RUNS_DIR.iterdir()):
        console.print("[dim]No hay features registrados aún.[/dim]")
        return

    table = Table(title="Features de la Fábrica de Software")
    table.add_column("Feature ID", style="dim", no_wrap=True)
    table.add_column("Nombre")
    table.add_column("Modo")
    table.add_column("Estado")
    table.add_column("Costo USD")

    status_colors = {
        "completado": "green", "aprobado": "cyan", "iniciando": "yellow",
        "detenido": "red", "awaiting_approval": "yellow",
        "paused_at_checkpoint_a": "yellow", "paused_at_checkpoint_b": "yellow",
    }

    for run_dir in sorted(RUNS_DIR.iterdir()):
        meta_path = run_dir / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        status = meta.get("status", "?")
        color = status_colors.get(status, "white")
        table.add_row(
            run_dir.name,
            meta.get("feature_name", "?")[:40],
            meta.get("mode", "?").upper(),
            f"[{color}]{status}[/{color}]",
            f"${meta.get('total_cost_usd', 0):.4f}",
        )

    console.print(table)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fábrica de Software Autónoma — Omni ERP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new-feature", help="Inicia un nuevo feature")
    p_new.add_argument("name", help="Nombre descriptivo del feature")
    p_new.add_argument("--repo", required=True,
                       help="Nombre del repositorio destino (ej: omni-erp)")
    p_new.add_argument("--lite", action="store_true",
                       help="Modo lite: bugfix sin DB/MCP (más rápido y económico)")

    p_resume = sub.add_parser("resume", help="Reanuda un pipeline pausado")
    p_resume.add_argument("feature_id", help="ID del feature a reanudar")

    p_status = sub.add_parser("status", help="Muestra el estado de un feature")
    p_status.add_argument("feature_id")

    sub.add_parser("list", help="Lista todos los features")
    sub.add_parser("repos", help="Lista los repositorios disponibles")

    args = parser.parse_args()

    if args.cmd == "new-feature":
        cmd_new_feature(args.name, args.lite, args.repo)
    elif args.cmd == "resume":
        cmd_resume(args.feature_id)
    elif args.cmd == "status":
        cmd_status(args.feature_id)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "repos":
        cmd_repos()


if __name__ == "__main__":
    main()
