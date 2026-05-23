"""
Auditor Periódico de Codebase — Fábrica de Software.

Corre de forma recurrente (configurable, default: lunes 7:00 AM Venezuela).
Para cada repositorio activo:

  1. Lee el ARCHITECTURE.md, CODING_STANDARDS y DECISION_LOG
  2. Escanea los archivos fuente más recientes/relevantes
  3. Usa un modelo IA para detectar:
       • Inconsistencias con la arquitectura definida
       • Deuda técnica acumulada
       • Violaciones de coding standards
       • Vulnerabilidades de seguridad (OWASP básico)
       • Naming inconsistente entre features
       • Código muerto o duplicado evidente
  4. Categoriza hallazgos por severidad: CRÍTICO / ALTO / MEDIO / INFO
  5. Envía informe por Telegram
  6. Escala al Founder si hay hallazgos CRÍTICOS

Configuración (env vars):
  AUDITOR_ENABLED   = true
  AUDITOR_WEEKDAY   = 0        (0=lunes … 6=domingo)
  AUDITOR_HOUR      = 7
  AUDITOR_MAX_FILES = 30       (máx archivos a analizar por repo)
  AUDITOR_MODEL     = claude-sonnet-4-6  (usa Anthropic por defecto)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return {
        "enabled":   os.getenv("AUDITOR_ENABLED",   "true").lower() == "true",
        "weekday":   int(os.getenv("AUDITOR_WEEKDAY", "0")),
        "hour":      int(os.getenv("AUDITOR_HOUR",    "7")),
        "max_files": int(os.getenv("AUDITOR_MAX_FILES", "30")),
        "model":     os.getenv("AUDITOR_MODEL", "claude-sonnet-4-6"),
        "api_key":   os.getenv("ANTHROPIC_API_KEY", ""),
        "tg_token":  os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "tg_chat":   os.getenv("TELEGRAM_CHAT_ID", ""),
    }


# ── Lectura del repositorio ───────────────────────────────────────────────────

_AUDIT_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", "coverage", "migrations"}
_CONTEXT_FILES = ["ARCHITECTURE.md", "CODING_STANDARDS.md", "DECISION_LOG.md",
                  "README.md", ".coding_standards", "coding_standards.md"]


def _read_context_docs(repo_path: str) -> str:
    """Lee ARCHITECTURE.md, CODING_STANDARDS, DECISION_LOG si existen."""
    docs = []
    p = Path(repo_path)
    for fname in _CONTEXT_FILES:
        f = p / fname
        if f.exists():
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")[:4000]
                docs.append(f"### {fname}\n{content}")
            except Exception:
                pass
    return "\n\n".join(docs) if docs else "(Sin documentos de arquitectura encontrados)"


def _collect_source_files(repo_path: str, max_files: int) -> list[Path]:
    """
    Recoge los archivos fuente más relevantes del repositorio.
    Prioriza los modificados recientemente; excluye tests y migraciones.
    """
    p = Path(repo_path)
    candidates: list[Path] = []

    for f in p.rglob("*"):
        if f.is_file() and f.suffix in _AUDIT_EXTENSIONS:
            parts = set(f.parts)
            if parts & _SKIP_DIRS:
                continue
            # Excluir archivos de test (no el código de producción)
            name = f.name.lower()
            if name.startswith("test_") or name.endswith("_test.py") or "/tests/" in str(f):
                continue
            candidates.append(f)

    # Ordenar por fecha de modificación (más recientes primero)
    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return candidates[:max_files]


def _build_source_snapshot(repo_path: str, max_files: int) -> str:
    """Construye un snapshot legible de los archivos fuente para el auditor."""
    files = _collect_source_files(repo_path, max_files)
    if not files:
        return "(Repositorio vacío o sin archivos fuente detectados)"

    parts = []
    total_chars = 0
    char_limit  = 60_000   # dejar margen para el prompt

    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            rel     = f.relative_to(repo_path)
            header  = f"\n### {rel} ({len(content)} chars)\n"
            snippet = content[:2000]   # máx 2000 chars por archivo
            if total_chars + len(snippet) > char_limit:
                parts.append(f"\n### {rel}\n[... truncado por límite de contexto ...]")
                break
            parts.append(header + snippet)
            total_chars += len(snippet)
        except Exception:
            pass

    return "\n".join(parts)


# ── Motor de análisis ─────────────────────────────────────────────────────────

def _call_auditor(prompt: str, model: str, api_key: str) -> str:
    """Llama a Anthropic para el análisis. Sin web_search — es análisis puro de código."""
    try:
        import anthropic
        client   = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(b.text for b in response.content if hasattr(b, "text")).strip()
    except Exception as e:
        logger.exception("Auditor: error llamando al modelo: %s", e)
        return f"[ERROR al generar análisis: {e}]"


def _build_prompt(
    repo_name: str,
    context_docs: str,
    source_snapshot: str,
    today: str,
) -> str:
    return f"""Eres un auditor de codebase experto. Hoy es {today}.

REPOSITORIO: {repo_name}

## DOCUMENTOS DE ARQUITECTURA Y ESTÁNDARES
{context_docs}

## SNAPSHOT DEL CÓDIGO FUENTE
{source_snapshot}

---

Tu tarea: audita este codebase en busca de problemas reales. Sé específico y cita archivos/líneas.

Analiza las siguientes dimensiones:

### 1. CONSISTENCIA CON ARQUITECTURA
¿El código implementado respeta el stack, patrones y convenciones definidos en ARCHITECTURE.md?
Detecta: uso de patrones incorrectos, violaciones de arquitectura en capas, deuda arquitectónica.

### 2. CALIDAD DE CÓDIGO
Detecta:
- Lógica de negocio en la capa equivocada (ej: en ViewSets en vez de Services)
- Funciones/clases duplicadas entre módulos
- Código muerto o comentado que ya no aplica
- Variables/funciones mal nombradas vs. el estándar definido

### 3. SEGURIDAD (OWASP básico)
Detecta:
- Broken Access Control: queries sin filtro multi-tenant, endpoints sin autenticación
- Inyección: SQL injection, command injection, XSS
- Secretos hardcodeados o configuración insegura
- Dependencias con versiones conocidamente vulnerables (si son visibles)

### 4. COHERENCIA INTER-FEATURE
Detecta:
- Clases/servicios duplicados con nombres distintos (UserService vs UserManager)
- Endpoints que se solapan
- Modelos DB con misma responsabilidad definidos dos veces

### 5. DEUDA TÉCNICA
TODOs/FIXMEs críticos, antipatrones acumulados, parches temporales que se volvieron permanentes.

---

## FORMATO DE RESPUESTA (OBLIGATORIO)

Usa este formato exacto para Telegram Markdown:

🔍 *AUDITORÍA — {repo_name}*
📅 _{today}_

📊 *RESUMEN:* [X] críticos · [Y] altos · [Z] medios · [N] informativos

🔴 *CRÍTICOS* (requieren acción inmediata):
[Lista numerada. Si no hay: "Ninguno detectado."]

🟠 *ALTOS* (resolver en próximo sprint):
[Lista numerada. Si no hay: "Ninguno detectado."]

🟡 *MEDIOS* (backlog técnico):
[Lista numerada, máx. 5]

ℹ️ *INFORMATIVOS*:
[Lista de 2-3 observaciones de mejora]

✅ *POSITIVO*:
[1-2 cosas bien implementadas]

---
_Auditor automático · Fábrica de Software_"""


# ── Telegram ──────────────────────────────────────────────────────────────────

def _send_tg(text: str, cfg: dict) -> bool:
    import httpx
    token = cfg["tg_token"]
    chat  = cfg["tg_chat"]
    if not token or not chat:
        return False
    try:
        # Telegram tiene límite de 4096 chars
        for i in range(0, len(text), 4000):
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[i:i+4000], "parse_mode": "Markdown"},
                timeout=15,
            )
        return True
    except Exception as e:
        logger.warning("Auditor Telegram error: %s", e)
        return False


# ── Estado global del auditor ─────────────────────────────────────────────────

import threading as _threading

_audit_lock    = _threading.Lock()
_audit_running = False   # True mientras hay una auditoría en curso

# Últimos resultados por repo: { repo_name: { report, started_at, finished_at, error } }
_last_results: dict[str, dict] = {}


def get_status() -> dict:
    """Devuelve el estado actual del auditor para la UI."""
    return {
        "running":      _audit_running,
        "last_results": {
            name: {
                "started_at":  r.get("started_at"),
                "finished_at": r.get("finished_at"),
                "error":       r.get("error"),
                # Primeras 500 chars para el resumen en lista
                "summary":     r.get("report", "")[:500],
            }
            for name, r in _last_results.items()
        },
    }


def get_result(repo_name: str) -> dict | None:
    """Devuelve el resultado completo de una auditoría (informe largo)."""
    return _last_results.get(repo_name)


# ── Punto de entrada ──────────────────────────────────────────────────────────

def _has_critical(report: str) -> bool:
    lower = report.lower()
    return any(k in lower for k in ("crítico", "critical", "🔴"))


def audit_repo(repo_name: str, repo_path: str) -> str:
    """
    Audita un repositorio y retorna el informe como string.
    No envía Telegram — eso lo hace run_audit().
    Actualiza _last_results con el resultado.
    """
    global _last_results
    cfg   = _cfg()
    today = datetime.now().strftime("%d/%m/%Y")
    started = datetime.now().isoformat()

    logger.info("Auditor: iniciando auditoría de '%s' en %s", repo_name, repo_path)
    _last_results[repo_name] = {
        "started_at":  started,
        "finished_at": None,
        "report":      "",
        "error":       None,
    }

    try:
        context_docs    = _read_context_docs(repo_path)
        source_snapshot = _build_source_snapshot(repo_path, cfg["max_files"])
        prompt          = _build_prompt(repo_name, context_docs, source_snapshot, today)
        report          = _call_auditor(prompt, cfg["model"], cfg["api_key"])
    except Exception as e:
        _last_results[repo_name]["error"] = str(e)
        _last_results[repo_name]["finished_at"] = datetime.now().isoformat()
        raise

    _last_results[repo_name]["report"]      = report
    _last_results[repo_name]["finished_at"] = datetime.now().isoformat()

    logger.info("Auditor: auditoría de '%s' completada (%d chars)", repo_name, len(report))
    return report


def run_audit(repo_filter: str = "all", send_telegram: bool = True) -> None:
    """
    Punto de entrada del scheduler y de auditorías on-demand.

    Args:
        repo_filter: "all" para auditar todos los repos, o el nombre exacto
                     de un repo específico (ej: "omni-erp").
        send_telegram: si False, ejecuta la auditoría pero no envía Telegram
                       (útil para pruebas o cuando se quiere solo el resultado en UI).
    """
    global _audit_running

    with _audit_lock:
        if _audit_running:
            logger.warning("Auditor: ya hay una auditoría en curso, ignorando solicitud")
            return
        _audit_running = True

    try:
        cfg = _cfg()
        logger.info("=== Auditoría de codebase iniciada (repo_filter=%s) ===", repo_filter)

        try:
            from config import list_repos
            all_repos = list_repos()
        except Exception as e:
            logger.exception("Auditor: error obteniendo repos: %s", e)
            return

        if not all_repos:
            logger.info("Auditor: sin repositorios configurados")
            return

        # Filtrar repos según repo_filter
        if repo_filter == "all":
            repos = all_repos
        else:
            repos = [r for r in all_repos if r["name"] == repo_filter]
            if not repos:
                logger.warning("Auditor: repo '%s' no encontrado en workspace", repo_filter)
                return

        today = datetime.now().strftime("%d/%m/%Y")

        if send_telegram:
            label = "todos los repos" if repo_filter == "all" else f"repo: {repo_filter}"
            header = (
                f"🏭 *AUDITORÍA — {today}*\n"
                f"_{len(repos)} repositorio(s) · {label}_\n\n"
            )
            _send_tg(header, cfg)

        any_critical = False
        for repo in repos:
            try:
                report = audit_repo(repo["name"], repo["path"])
                if send_telegram:
                    _send_tg(report, cfg)
                if _has_critical(report):
                    any_critical = True
            except Exception as e:
                logger.exception("Auditor: error en repo '%s': %s", repo["name"], e)
                if send_telegram:
                    _send_tg(f"❌ Error auditando `{repo['name']}`: {e}", cfg)

        if send_telegram and any_critical:
            _send_tg(
                "⚠️ *ATENCIÓN — Hallazgos críticos detectados*\n\n"
                "La auditoría encontró issues críticos en al menos un repositorio.\n"
                "Revisa los reportes anteriores y planifica correcciones en el próximo sprint.\n\n"
                "Puedes solicitar correcciones con:\n"
                "`/feature <repo>: Corrección deuda técnica auditoría semanal`",
                cfg,
            )

        logger.info("=== Auditoría completada (%d repos) ===", len(repos))

    finally:
        _audit_running = False
