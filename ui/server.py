"""
Servidor web de la Fábrica de Software — Omni ERP.
Arrancar: uvicorn ui.server:app --reload --port 7860
"""
from __future__ import annotations
import sys
import json
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator

import aiofiles
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Asegurar imports del orquestador
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import RUNS_DIR, PRICES, MODEL_PM, MODEL_STANDARD, MODEL_FAST, DB_PATH, list_repos, FABRICA_DIR
from ui.config_store import ConfigStore

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Fábrica de Software", docs_url=None, redoc_url=None)

_UI_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=_UI_DIR / "static"), name="static")
templates = Jinja2Templates(directory=_UI_DIR / "templates")
store = ConfigStore()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    runs = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        meta["feature_id"] = d.name
        meta["outputs"] = [p.name for p in sorted(d.glob("output_*.md"))]
        runs.append(meta)
    return runs


def _total_cost(runs: list[dict]) -> float:
    return sum(r.get("total_cost_usd", 0) for r in runs)


def _cost_by_status(runs: list[dict]) -> dict:
    buckets: dict[str, float] = {}
    for r in runs:
        s = r.get("status", "?")
        buckets[s] = buckets.get(s, 0) + r.get("total_cost_usd", 0)
    return buckets


# ── Rutas — Dashboard ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    runs = _all_runs()
    return templates.TemplateResponse(request, "dashboard.html", {
        "runs": runs,
        "total_cost": _total_cost(runs),
        "cost_by_status": _cost_by_status(runs),
        "active_page": "dashboard",
    })


# ── Rutas — Configuración ─────────────────────────────────────────────────────

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, saved: str = ""):
    cfg = store.load()
    return templates.TemplateResponse(request, "config.html", {
        "cfg": cfg,
        "prices": PRICES,
        "active_page": "config",
        "saved": saved == "1",
    })


@app.post("/config")
async def save_config(
    request: Request,
    # API keys
    anthropic_api_key: str = Form(""),
    google_api_key:    str = Form(""),
    zhipu_api_key:     str = Form(""),
    kimi_api_key:      str = Form(""),
    langchain_api_key: str = Form(""),
    langchain_tracing: str = Form("false"),
    # Modelos por agente
    model_a1: str = Form("gemini-3.1-pro-preview"),
    model_a2: str = Form("glm-5.1"),
    model_a3: str = Form("kimi-k2.6"),
    model_a4: str = Form(MODEL_STANDARD),
    model_a5: str = Form(MODEL_STANDARD),
    model_a6: str = Form(MODEL_STANDARD),
    model_a7: str = Form(MODEL_STANDARD),
    model_a8: str = Form(MODEL_STANDARD),
    # Límites
    max_qa_completo:    int = Form(3),
    max_qa_lite:        int = Form(2),
    checkpoint_timeout: int = Form(1800),
):
    # ConfigStore.save() ignora keys enmascaradas automáticamente
    new_cfg = {
        "ANTHROPIC_API_KEY": anthropic_api_key,
        "GOOGLE_API_KEY":    google_api_key,
        "ZHIPU_API_KEY":     zhipu_api_key,
        "KIMI_API_KEY":      kimi_api_key,
        "LANGCHAIN_API_KEY": langchain_api_key,
        "LANGCHAIN_TRACING_V2": "true" if langchain_tracing == "on" else "false",
        "MODEL_A1": model_a1,
        "MODEL_A2": model_a2,
        "MODEL_A3": model_a3,
        "MODEL_A4": model_a4,
        "MODEL_A5": model_a5,
        "MODEL_A6": model_a6,
        "MODEL_A7": model_a7,
        "MODEL_A8": model_a8,
        "MAX_QA_ITER_COMPLETO":       max_qa_completo,
        "MAX_QA_ITER_LITE":           max_qa_lite,
        "CHECKPOINT_TIMEOUT_SECONDS": checkpoint_timeout,
    }
    store.save(new_cfg)
    return RedirectResponse("/config?saved=1", status_code=303)


# ── Rutas — Nuevo Feature ─────────────────────────────────────────────────────

@app.get("/new", response_class=HTMLResponse)
async def new_feature_page(request: Request):
    cfg = store.load()
    api_key_ok = bool(cfg.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))
    repos = list_repos()
    return templates.TemplateResponse(request, "new_feature.html", {
        "active_page": "new",
        "api_key_ok": api_key_ok,
        "repos": repos,
    })


# ── Rutas — Nuevo Proyecto ────────────────────────────────────────────────────

@app.get("/project/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    cfg = store.load()
    api_key_ok = bool(cfg.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))
    repos = list_repos()
    return templates.TemplateResponse(request, "new_project.html", {
        "active_page": "new_project",
        "api_key_ok": api_key_ok,
        "repos": repos,
    })


@app.post("/project/new")
async def start_project(
    project_name: str = Form(...),
    project_brief: str = Form(...),
    repo_name: str = Form(...),
    is_new_project: str = Form("false"),
):
    if not project_name.strip():
        raise HTTPException(400, "El nombre del proyecto no puede estar vacío")
    if not project_brief.strip():
        raise HTTPException(400, "El brief del proyecto no puede estar vacío")

    import os
    project_id = (
        f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{project_name.strip()[:20].replace(' ', '_').lower()}"
    )

    is_new = is_new_project.lower() in ("true", "1", "on")
    lite_flag  = ["--new"] if is_new else []
    cmd = [
        sys.executable, "cli.py", "new-project",
        project_name.strip(),
        project_brief.strip(),
        "--repo", repo_name.strip(),
    ] + lite_flag

    (RUNS_DIR / project_id).mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / project_id / "process.pid").write_text("starting")

    subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**__import__("os").environ, "PROJECT_ID_OVERRIDE": project_id},
    )

    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    run_dir = RUNS_DIR / project_id
    if not run_dir.exists():
        raise HTTPException(404, "Proyecto no encontrado")

    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    return templates.TemplateResponse(request, "project_detail.html", {
        "project_id": project_id,
        "meta": meta,
        "active_page": "dashboard",
    })


@app.post("/project/{project_id}/approve-roadmap")
async def approve_roadmap(project_id: str, action: str = Form("approve")):
    """Aprueba o cancela el roadmap desde la UI."""
    run_dir = RUNS_DIR / project_id
    approval_file = run_dir / "pending_approval.txt"
    approval_file.write_text(action)
    return JSONResponse({"ok": True, "action": action})


# ── Rutas — Nuevo Feature ─────────────────────────────────────────────────────

@app.post("/new")
async def start_feature(
    feature_name: str = Form(...),
    mode: str = Form("auto"),
    repo_name: str = Form(...),
):
    if not feature_name.strip():
        raise HTTPException(400, "El nombre del feature no puede estar vacío")
    if not repo_name.strip():
        raise HTTPException(400, "Debes seleccionar un repositorio")

    # El feature_id se genera en cli.py — llamamos al proceso
    cmd = [
        sys.executable, "cli.py", "new-feature",
        feature_name.strip(),
        "--repo", repo_name.strip(),
        "--mode", mode,
    ]
    # Lanzar en background — el usuario verá el progreso en /stream/<feature_id>
    # Generamos el feature_id anticipado para poder redirigir
    feature_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{feature_name.strip()[:20].replace(' ', '_').lower()}"
    )
    env_path = Path(__file__).parent.parent / ".env"
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**__import__("os").environ, "FEATURE_ID_OVERRIDE": feature_id},
    )
    # Guardar PID para status
    (RUNS_DIR / feature_id).mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / feature_id / "process.pid").write_text(str(proc.pid))

    return RedirectResponse(f"/feature/{feature_id}", status_code=303)


# ── Rutas — Detalle de Feature ────────────────────────────────────────────────

@app.get("/feature/{feature_id}", response_class=HTMLResponse)
async def feature_detail(request: Request, feature_id: str):
    run_dir = RUNS_DIR / feature_id
    if not run_dir.exists():
        raise HTTPException(404, "Feature no encontrado")

    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    outputs = {}
    for p in sorted(run_dir.glob("output_*.md")):
        outputs[p.stem.replace("output_", "")] = p.read_text(encoding="utf-8")

    master_plan = ""
    mp_path = run_dir / "MASTER_PLAN.md"
    if mp_path.exists():
        master_plan = mp_path.read_text(encoding="utf-8")

    return templates.TemplateResponse(request, "feature_detail.html", {
        "feature_id": feature_id,
        "meta": meta,
        "outputs": outputs,
        "master_plan": master_plan,
        "active_page": "dashboard",
    })


# ── Rutas — Resume (aprobación del Stop Protocol desde la UI) ────────────────

@app.post("/feature/{feature_id}/approve")
async def approve_feature(feature_id: str, action: str = Form("approve")):
    """Permite aprobar el MASTER_PLAN o pausar checkpoints desde la UI."""
    run_dir = RUNS_DIR / feature_id
    approval_file = run_dir / "pending_approval.txt"
    approval_file.write_text(action)
    return JSONResponse({"ok": True, "action": action})


# ── Rutas — API de datos (para gráficas JS) ───────────────────────────────────

@app.get("/api/costs")
async def api_costs():
    runs = _all_runs()
    daily: dict[str, float] = {}
    for r in runs:
        day = (r.get("started_at") or "")[:10]
        if day:
            daily[day] = round(daily.get(day, 0) + r.get("total_cost_usd", 0), 6)

    by_agent: dict[str, float] = {}
    for run_dir in RUNS_DIR.iterdir() if RUNS_DIR.exists() else []:
        meta_path = run_dir / "metadata.json"
        if not meta_path.exists():
            continue
        # Extraer entries de costo si están guardadas
        entries_path = run_dir / "cost_entries.json"
        if entries_path.exists():
            for e in json.loads(entries_path.read_text()):
                ag = e.get("agent", "?")
                by_agent[ag] = round(by_agent.get(ag, 0) + e.get("cost_usd", 0), 6)

    return {
        "total": _total_cost(runs),
        "total_runs": len(runs),
        "daily": daily,
        "by_agent": by_agent,
        "runs": [
            {
                "id": r["feature_id"],
                "name": r.get("feature_name", r["feature_id"]),
                "status": r.get("status", "?"),
                "cost": r.get("total_cost_usd", 0),
                "mode": r.get("mode", "?"),
                "date": (r.get("started_at") or "")[:19],
            }
            for r in runs[:20]
        ],
    }


@app.get("/api/feature/{feature_id}/status")
async def api_feature_status(feature_id: str):
    meta_path = RUNS_DIR / feature_id / "metadata.json"
    if not meta_path.exists():
        return {"status": "not_found"}
    return json.loads(meta_path.read_text())


# ── SSE — Stream de logs en tiempo real ───────────────────────────────────────

@app.get("/stream/{feature_id}")
async def stream_logs(feature_id: str):
    """Server-Sent Events: emite líneas del log del feature en tiempo real."""
    run_dir = RUNS_DIR / feature_id

    async def event_generator() -> AsyncIterator[str]:
        log_path = run_dir / "run.log"
        sent_lines = 0
        idle_ticks = 0

        while idle_ticks < 120:  # timeout 2 min sin nuevas líneas
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8").splitlines()
                new_lines = lines[sent_lines:]
                for line in new_lines:
                    yield f"data: {line}\n\n"
                    sent_lines += len(lines)
                if new_lines:
                    idle_ticks = 0

            # Verificar si el proceso terminó
            meta_path = run_dir / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                status = meta.get("status", "")
                if status in ("completado", "detenido", "aprobado"):
                    yield f"data: [DONE] status={status}\n\n"
                    return

            idle_ticks += 1
            await asyncio.sleep(1)

        yield "data: [TIMEOUT]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
