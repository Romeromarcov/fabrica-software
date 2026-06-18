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

def cmd_new_feature(feature_name: str, mode: str, repo_name: str) -> None:
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
        f"Modo: [yellow]{mode.upper()}[/yellow]{'  [dim](el PM decide)[/dim]' if mode == 'auto' else ''}\n"
        f"ID: [dim]{feature_id}[/dim]",
        title="🏭 Fábrica de Software"
    ))

    # VII-1: cargar refined_brief del pre-chat si existe
    refined_brief = os.environ.get("REFINED_BRIEF_OVERRIDE", "").strip() or None
    if not refined_brief:
        # Fallback: leerlo de metadata si el servidor ya lo guardó
        try:
            import json as _json
            from tools.file_tools import RUNS_DIR as _RUNS_DIR
            _meta_path = _RUNS_DIR / feature_id / "metadata.json"
            if _meta_path.exists():
                _meta = _json.loads(_meta_path.read_text())
                refined_brief = _meta.get("refined_brief") or None
        except Exception:
            pass

    state = initial_state(feature_id, feature_name, mode, repo_name, repo_path)
    if refined_brief:
        state["refined_brief"] = refined_brief
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
    from langgraph.types import Command
    tipo = interrupt_data.get("tipo", "unknown")

    if tipo == "stop_protocol":
        console.print(Panel(
            Markdown(interrupt_data.get("mensaje", "")),
            title="⛔ STOP PROTOCOL — Agente 1",
            border_style="red"
        ))
        console.print("\n[bold]Tu respuesta:[/bold] ", end="")
        respuesta = input().strip()

        # Reanudar el grafo — el nodo recibe respuesta via interrupt() y calcula founder_approval
        for chunk in app.stream(
            Command(resume=respuesta),
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

        for chunk in app.stream(
            Command(resume=respuesta),
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
        for chunk in app.stream(
            Command(resume=respuesta),
            config=config,
            stream_mode="updates",
        ):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                _handle_interrupt(app, config, chunk[node_name][0].value, feature_id)
                return
            _print_node_progress(node_name, chunk[node_name])


def _print_node_progress(node_name: str, output: dict) -> None:
    agent = output.get("current_agent", node_name)
    labels = {
        "a1_planificador":         "📋 A1 — Planificador",
        "confidence_auto_approve": "✅ Auto-aprobado",
        "stop_protocol":           "⛔ Stop Protocol",
        "a2_db":                   "🗄️  A2 — DB Architect",
        "a3_mcp":                  "🔧 A3 — MCP Toolsmith",
        "a4_backend":              "⚙️  A4 — Backend",
        "a5_frontend":             "🖥️  A5 — Frontend",
        "a6_refactor":             "✨ A6 — Revisor/Unificador",
        "a7_qa":                   "🧪 A7 — QA",
        "qa_escalation":           "⚠️  QA Escalation",
        "a8_secops":               "🔒 A8 — SecOps",
        "a10_code_writer":         "💾 A10 — Code Writer",
        "a1_pr_final":             "📦 A1 — PR Final",
        "lightning_complete":      "⚡ Lightning completado",
        "pipeline_detenido":       "🚫 Pipeline Detenido",
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


# ── Comando: new-project ─────────────────────────────────────────────────────

def cmd_new_project(name: str, brief: str, repo_name: str, new: bool, audit: bool = False) -> None:
    from project_state import initial_project_state
    from tools.file_tools import save_run_metadata
    from config import resolve_repo_path, list_repos

    available = [r["name"] for r in list_repos()]
    if repo_name not in available:
        console.print(f"[red]Repositorio '{repo_name}' no encontrado.[/red]")
        console.print(f"[dim]Disponibles: {', '.join(available) or 'ninguno'}[/dim]")
        sys.exit(1)

    repo_path  = resolve_repo_path(repo_name)
    project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name[:20].replace(' ', '_').lower()}"

    import os
    project_id = os.environ.get("PROJECT_ID_OVERRIDE", project_id)

    console.print(Panel(
        f"[bold cyan]Nuevo Proyecto[/bold cyan]\n"
        f"Nombre: [cyan]{name}[/cyan]\n"
        f"Repo: [magenta]{repo_name}[/magenta]\n"
        f"Tipo: [yellow]{'Nuevo desde cero' if new else 'Plan para repo existente'}[/yellow]\n"
        f"ID: [dim]{project_id}[/dim]",
        title="🏗️ Fábrica de Software — Project Loop"
    ))

    from graph_project import compile_project_graph
    state  = initial_project_state(
        project_id, name, brief, repo_name, repo_path,
        is_new_project=new, audit_mode=audit,
    )
    app    = compile_project_graph()
    config = _thread_config(project_id)

    save_run_metadata(project_id, {
        "project_id":     project_id,
        "project_name":   name,
        "repo_name":      repo_name,
        "is_new_project": new,
        "audit_mode":     audit,
        "project_status": "planning",
        "started_at": datetime.utcnow().isoformat(),
    })

    console.print(f"\n[dim]Iniciando Agente 0 (Arquitecto)...[/dim]")

    try:
        for chunk in app.stream(state, config=config, stream_mode="updates"):
            node_name  = list(chunk.keys())[0]
            node_output = chunk[node_name]

            if node_name == "__interrupt__":
                interrupt_data = node_output[0].value
                _handle_project_interrupt(app, config, interrupt_data, project_id)
                return

            _print_project_progress(node_name, node_output)

    except KeyboardInterrupt:
        console.print("\n[yellow]Proyecto pausado. Usa 'resume-project' para continuar.[/yellow]")
        console.print(f"[dim]Project ID: {project_id}[/dim]")


def _wait_for_approval_file(project_id: str, interrupt_type: str) -> str:
    """
    BUG-009: En modo UI (subprocess), espera que el servidor escriba pending_approval.txt.
    Devuelve el contenido del archivo (acción del usuario).
    """
    import time
    from tools.file_tools import RUNS_DIR
    run_dir = RUNS_DIR / project_id
    approval_file = run_dir / "pending_approval.txt"

    # Guardar el tipo de interrupción para que la UI pueda mostrarlo
    (run_dir / "pending_interrupt_type.txt").write_text(interrupt_type)

    console.print(f"[dim]Esperando respuesta desde la UI para: {interrupt_type}...[/dim]")
    # C-01 fix: máximo 4 horas de espera (7200 s / 2 s por tick = 3600 ticks)
    max_ticks = int(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "14400")) // 2
    for _ in range(max_ticks):
        if approval_file.exists():
            action = approval_file.read_text().strip()
            approval_file.unlink()
            (run_dir / "pending_interrupt_type.txt").unlink(missing_ok=True)
            return action
        time.sleep(2)
    # Timeout alcanzado — limpiar y cancelar
    (run_dir / "pending_interrupt_type.txt").unlink(missing_ok=True)
    console.print("[red]Timeout: sin respuesta del Founder. Cancelando.[/red]")
    return "CANCELAR"


def _handle_project_interrupt(app, config: dict, interrupt_data: dict, project_id: str) -> None:
    from langgraph.types import Command

    tipo = interrupt_data.get("tipo", "unknown")
    # Detectar si corremos como subprocess desde la UI
    ui_mode = bool(os.environ.get("PROJECT_ID_OVERRIDE"))

    if tipo == "project_roadmap_approval":
        if ui_mode:
            action = _wait_for_approval_file(project_id, tipo)
            # La UI escribe "approve"/"cancel"; el bot puede enviar texto libre (cambios)
            if action == "approve":
                respuesta = "Roadmap aprobado. Iniciar proyecto."
            elif action == "cancel":
                respuesta = "CANCELAR"
            else:
                respuesta = action   # feedback libre desde Telegram o CLI
        else:
            console.print(Panel(
                Markdown(interrupt_data.get("mensaje", "")),
                title="📐 Roadmap listo — Revisión requerida",
                border_style="cyan",
            ))
            console.print("\n[bold]Tu respuesta:[/bold] ", end="")
            respuesta = input().strip()

        for chunk in app.stream(
            Command(resume=respuesta),   # BUG-014: Command(resume=...) no string directo
            config=config, stream_mode="updates",
        ):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                _handle_project_interrupt(app, config, chunk[node_name][0].value, project_id)
                return
            _print_project_progress(node_name, chunk[node_name])

    elif tipo == "project_suggestions":
        if ui_mode:
            action = _wait_for_approval_file(project_id, tipo)
            # La UI escribe "CONTINUAR"/"CERRAR"/"PAUSA"; el bot puede enviar texto libre
            upper = action.upper()
            if upper in ("CONTINUAR", "CERRAR", "PAUSA"):
                respuesta = upper
            else:
                respuesta = action   # texto libre desde Telegram
        else:
            console.print(Panel(
                interrupt_data.get("mensaje", ""),
                title="💡 Sugerencias del PM",
                border_style="yellow",
            ))
            console.print("[bold]Tu decisión (CONTINUAR / CERRAR / PAUSA):[/bold] ", end="")
            respuesta = input().strip()

        for chunk in app.stream(
            Command(resume=respuesta),   # BUG-014: Command(resume=...) no string directo
            config=config, stream_mode="updates",
        ):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                _handle_project_interrupt(app, config, chunk[node_name][0].value, project_id)
                return
            _print_project_progress(node_name, chunk[node_name])


def _print_project_progress(node_name: str, output: dict) -> None:
    labels = {
        "a0_arquitecto":        "📐 A0 — Arquitecto",
        "human_approve_roadmap":"⛔ Esperando aprobación de roadmap",
        "pick_next_feature":    "🎯 Seleccionando siguiente feature",
        "run_feature_pipeline": "⚙️  Ejecutando pipeline de feature",
        "pm_evaluador":         "🔍 PM Evaluador",
        "advance_index":        "→  Avanzando",
        "present_suggestions":  "💡 Sugerencias del PM",
        "project_complete":     "🏁 Proyecto completado",
    }
    label = labels.get(node_name, f"⚡ {node_name}")
    costs = output.get("cost_entries", [])
    cost_str = f" [dim](${sum(e.get('cost_usd',0) for e in costs):.4f})[/dim]" if costs else ""
    errors = output.get("errors", [])

    # Mostrar feature actual si está disponible
    backlog = output.get("backlog", [])
    idx     = output.get("current_feature_index")
    feat_str = ""
    if idx is not None and backlog and idx < len(backlog):
        feat_str = f" [dim]→ {backlog[idx]['name'][:40]}[/dim]"

    if errors:
        console.print(f"  {label} [red]✗[/red]{cost_str}")
    else:
        console.print(f"  {label} [green]✓[/green]{feat_str}{cost_str}")


# ── Comando: resume-project ───────────────────────────────────────────────────

def cmd_resume_project(project_id: str) -> None:
    from tools.file_tools import read_run_metadata
    meta = read_run_metadata(project_id)
    if not meta:
        console.print(f"[red]Proyecto no encontrado: {project_id}[/red]")
        return

    console.print(Panel(
        f"Reanudando proyecto: [cyan]{meta.get('project_name', project_id)}[/cyan]\n"
        f"Estado: [yellow]{meta.get('project_status', '?')}[/yellow]\n"
        f"Progreso: {meta.get('features_completed', '?')}/{meta.get('features_total', '?')} features",
        title="🔄 Resumiendo Project Loop",
    ))

    from graph_project import compile_project_graph
    app    = compile_project_graph()
    config = _thread_config(project_id)

    for chunk in app.stream(None, config=config, stream_mode="updates"):
        node_name = list(chunk.keys())[0]
        if node_name == "__interrupt__":
            _handle_project_interrupt(app, config, chunk[node_name][0].value, project_id)
            return
        _print_project_progress(node_name, chunk[node_name])


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


# ── M2: replay / debugging ──────────────────────────────────────────────────

def cmd_replay(feature_id: str, from_node: str | None) -> None:
    """Inspecciona los checkpoints de un feature o muestra el plan de replay."""
    from tools.replay import list_checkpoints, format_replay_plan

    checkpoints = list_checkpoints(feature_id)
    if not checkpoints:
        console.print(f"[yellow]Sin checkpoints para '{feature_id}' "
                      f"(¿feature inexistente o sin salidas guardadas?).[/yellow]")
        return

    if not from_node:
        console.print(Panel(
            "\n".join(f"• {c}" for c in checkpoints),
            title=f"Checkpoints de {feature_id}",
            subtitle="usa --from <nodo> para ver el plan de replay",
        ))
        return

    console.print(format_replay_plan(feature_id, from_node))


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
    p_new.add_argument("--mode", choices=["auto", "completo", "lite", "lightning"], default="auto",
                       help="Modo de ejecución (default: auto — el PM decide). "
                            "lightning: ultra-rápido para hotfixes/prototipos (sin QA/SecOps).")

    p_resume = sub.add_parser("resume", help="Reanuda un pipeline pausado")
    p_resume.add_argument("feature_id", help="ID del feature a reanudar")

    p_status = sub.add_parser("status", help="Muestra el estado de un feature")
    p_status.add_argument("feature_id")

    sub.add_parser("list", help="Lista todos los features")
    sub.add_parser("repos", help="Lista los repositorios disponibles")

    p_proj = sub.add_parser("new-project", help="Crea un plan de proyecto y arranca el loop autónomo")
    p_proj.add_argument("name",  help="Nombre del proyecto")
    p_proj.add_argument("brief", help="Descripción del objetivo del proyecto (entre comillas)")
    p_proj.add_argument("--repo", required=True, help="Repositorio destino")
    p_proj.add_argument("--new",  action="store_true",
                        help="Proyecto desde cero (A0 propone stack + arquitectura)")
    p_proj.add_argument("--audit", action="store_true",
                        help="V-1: Modo auditoría — onboarding profundo de repo existente sin docs")

    p_rp = sub.add_parser("resume-project", help="Reanuda un Project Loop pausado")
    p_rp.add_argument("project_id")

    # M2 (PLAN_PLATAFORMA_V2) — replay/debugging: inspecciona checkpoints y plan de replay.
    p_replay = sub.add_parser("replay", help="Muestra el plan de replay de un feature desde un nodo")
    p_replay.add_argument("feature_id")
    p_replay.add_argument("--from", dest="from_node", default=None,
                          help="Nodo desde el que re-ejecutar (ej: a6_refactor). "
                               "Sin valor → lista los checkpoints disponibles.")

    args = parser.parse_args()

    if args.cmd == "new-feature":
        cmd_new_feature(args.name, args.mode, args.repo)
    elif args.cmd == "resume":
        cmd_resume(args.feature_id)
    elif args.cmd == "status":
        cmd_status(args.feature_id)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "repos":
        cmd_repos()
    elif args.cmd == "new-project":
        cmd_new_project(args.name, args.brief, args.repo, args.new, audit=getattr(args, "audit", False))
    elif args.cmd == "resume-project":
        cmd_resume_project(args.project_id)
    elif args.cmd == "replay":
        cmd_replay(args.feature_id, args.from_node)


if __name__ == "__main__":
    main()
