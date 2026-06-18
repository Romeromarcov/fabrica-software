"""Configuración central del orquestador. Un solo lugar para cambiar modelos y rutas."""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
# Config persistida en el volumen (Railway): si la UI guardó keys en /data/.env,
# tiene prioridad sobre el .env del repo y sobre el entorno inyectado.
_VOL_ENV = Path(os.environ.get("CONFIG_ENV_PATH", "/data/.env"))
if _VOL_ENV.is_file():
    load_dotenv(_VOL_ENV, override=True)

# ── Rutas de la fábrica ───────────────────────────────────────────────────────
FABRICA_DIR = Path(__file__).parent
RUNS_DIR    = Path(os.getenv("RUNS_DIR", str(FABRICA_DIR / "data" / "runs")))
DB_PATH     = Path(os.getenv("DB_PATH",  str(FABRICA_DIR / "data" / "fabrica_state.db")))

# ── Multi-repo: directorio raíz donde viven todos los proyectos ───────────────
# En Docker: /workspace = C:\Users\PC\Proyectos
# En Windows nativo: configura WORKSPACES_ROOT en .env (ej: C:\Users\PC\Proyectos)
_ws_default = "/workspace" if os.name != "nt" else str(Path.home() / "Proyectos")
WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", _ws_default))


def list_repos() -> list[dict]:
    """Descubre repos git disponibles bajo WORKSPACES_ROOT."""
    repos = []
    if not WORKSPACES_ROOT.exists():
        # BUG-020: advertencia explícita en lugar de fallo silencioso
        import warnings
        warnings.warn(
            f"WORKSPACES_ROOT no existe: {WORKSPACES_ROOT}. "
            f"Configura la variable en .env (ej: WORKSPACES_ROOT=C:\\Users\\PC\\Proyectos)",
            stacklevel=2,
        )
        return repos
    for d in sorted(WORKSPACES_ROOT.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists():
            repos.append({"name": d.name, "path": str(d)})
    return repos


def resolve_repo_path(repo_name: str) -> str:
    """Devuelve la ruta absoluta del repo dentro del workspace."""
    return str(WORKSPACES_ROOT / repo_name)


# ── Clone-on-startup: repos destino a clonar/actualizar al arrancar ───────────
# Formato de TARGET_REPOS (separados por coma):
#   "omni-erp=https://github.com/org/omni-erp.git#main, otro=https://github.com/org/otro.git"
# Cada item: [nombre=]url[#rama]. Si no hay nombre, se deriva de la URL.
# El token (GITHUB_TOKEN) se inyecta en runtime; NUNCA va aquí.
TARGET_REPOS = os.getenv("TARGET_REPOS", "")


def parse_target_repos() -> list[dict]:
    """Parsea TARGET_REPOS → [{name, url, branch}]."""
    out: list[dict] = []
    for item in (TARGET_REPOS or "").split(","):
        item = item.strip()
        if not item:
            continue
        name, url, branch = "", item, ""
        # name=url  (evitar partir el '://' de la URL)
        if "=" in item.split("://", 1)[0]:
            name, url = item.split("=", 1)
        # url#branch
        if "#" in url:
            url, branch = url.split("#", 1)
        if not name:
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
        out.append({"name": name.strip(), "url": url.strip(), "branch": branch.strip()})
    return out


# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY",    "")
ZHIPU_API_KEY     = os.getenv("ZHIPU_API_KEY",     "")
KIMI_API_KEY      = os.getenv("KIMI_API_KEY",      "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY",    "")
NVIDIA_API_KEY    = os.getenv("NVIDIA_API_KEY",    "")   # build.nvidia.com (Nemotron)

# ── Modelo por agente ─────────────────────────────────────────────────────────
# Default unificado: todos los agentes con LLM apuntan al modelo más económico disponible
# (Google Gemini flash-lite). Cada uno sigue siendo overridable por env (MODEL_A*) y la
# clave del proveedor va en GOOGLE_API_KEY (.env, nunca commiteada).
_DEFAULT_AGENT_MODEL = "gemini-2.5-flash-lite"
MODEL_A0 = os.getenv("MODEL_A0", _DEFAULT_AGENT_MODEL)   # A0 Arquitecto de Proyecto
MODEL_A1 = os.getenv("MODEL_A1", _DEFAULT_AGENT_MODEL)   # A1 PM / Planificador
MODEL_A2 = os.getenv("MODEL_A2", _DEFAULT_AGENT_MODEL)   # A2 DB Architect
MODEL_A3 = os.getenv("MODEL_A3", _DEFAULT_AGENT_MODEL)   # A3 MCP Toolsmith
MODEL_A4 = os.getenv("MODEL_A4", _DEFAULT_AGENT_MODEL)   # A4 Backend Developer
MODEL_A5 = os.getenv("MODEL_A5", _DEFAULT_AGENT_MODEL)   # A5 Frontend Developer
MODEL_A6 = os.getenv("MODEL_A6", _DEFAULT_AGENT_MODEL)   # A6 Revisor / Refactor
MODEL_A7 = os.getenv("MODEL_A7", _DEFAULT_AGENT_MODEL)   # A7 QA Test
MODEL_A8 = os.getenv("MODEL_A8", _DEFAULT_AGENT_MODEL)   # A8 SecOps

MODEL_A9  = "no-llm"                                         # A9 Sandbox — sin LLM
MODEL_A10 = "no-llm"                                         # A10 Code Writer — sin LLM
MODEL_A11 = os.getenv("MODEL_A11", _DEFAULT_AGENT_MODEL)    # A11 DevOps
MODEL_A0_REVISOR = MODEL_A0                                  # A0 Revisor usa el mismo modelo que A0

MODEL_PM       = MODEL_A1
MODEL_STANDARD = _DEFAULT_AGENT_MODEL
MODEL_FAST     = os.getenv("MODEL_FAST", _DEFAULT_AGENT_MODEL)

# ── V2 Fase 0: modelo por defecto global (último escalón de la cascada) ────────
# Resolución de modelo por agente: agent.model → pipeline.default_model → GLOBAL_DEFAULT_MODEL.
# El modelo por agente sigue siendo OPCIONAL (invariante del PLAN_PLATAFORMA_V2).
GLOBAL_DEFAULT_MODEL = os.getenv("GLOBAL_DEFAULT_MODEL", MODEL_STANDARD)

# ── Flags de comportamiento del pipeline ──────────────────────────────────────
# WRITE_TO_REPO: si False, A10 hace dry-run (loguea sin escribir)
WRITE_TO_REPO = os.getenv("WRITE_TO_REPO", "true").lower() == "true"

# ── Límites del pipeline ──────────────────────────────────────────────────────
MAX_QA_ITER_COMPLETO       = int(os.getenv("MAX_QA_ITER_COMPLETO",       "3"))
MAX_QA_ITER_LITE           = int(os.getenv("MAX_QA_ITER_LITE",           "2"))
MAX_SECOPS_ITER            = int(os.getenv("MAX_SECOPS_ITER",            "2"))
MAX_SANDBOX_ITER           = int(os.getenv("MAX_SANDBOX_ITER",           "2"))
CHECKPOINT_TIMEOUT_SECONDS = int(os.getenv("CHECKPOINT_TIMEOUT_SECONDS", "1800"))

# ── Auditoría arquitectónica (A0 Revisor) ─────────────────────────────────────
# Cada cuántos features completados corre el A0 Revisor (0 = desactivado)
ARCH_REVIEW_INTERVAL = int(os.getenv("ARCH_REVIEW_INTERVAL", "3"))

# ── VII-1: Pre-planificación chat ────────────────────────────────────────────
# Si True, el botón "Nuevo Feature" redirige al chat pre-planificación antes de A1.
PRECHAT_ENABLED = os.getenv("PRECHAT_ENABLED", "true").lower() == "true"

# ── VIII-3: Debate inter-agente (panel de revisión para riesgo ALTO) ──────────
# Si True, los features con risk_level=HIGH (y modo != lightning) pasan por un
# panel de 2 revisores + árbitro A1 antes de la aprobación. Opt-in: añade ~3x el
# costo de LLM del plan (3 llamadas extra). Default seguro: false (debate omitido).
DEBATE_PANEL_ENABLED = os.getenv("DEBATE_PANEL_ENABLED", "false").lower() == "true"
# Modelo de los revisores/árbitro del debate. Por defecto usa el modelo económico
# (MODEL_FAST ≈ Haiku) para mantener el costo del debate bajo.
MODEL_DEBATE = os.getenv("MODEL_DEBATE", MODEL_FAST)

# ── VII-3: Railway Deploy ─────────────────────────────────────────────────────
RAILWAY_TOKEN      = os.getenv("RAILWAY_TOKEN",      "")
RAILWAY_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")
RAILWAY_ENABLED    = bool(RAILWAY_TOKEN and RAILWAY_PROJECT_ID)

# ── P0-B: GitHub OAuth 2.0 ───────────────────────────────────────────────────
# Si están configurados, el flujo OAuth reemplaza el PAT manual.
# Crear OAuth App en github.com → Settings → Developer Settings → OAuth Apps
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID",     "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_SECRET  = os.getenv("GITHUB_OAUTH_SECRET",  "fabrica-dev-secret-change-me")
GITHUB_OAUTH_CALLBACK = os.getenv(
    "GITHUB_OAUTH_CALLBACK_URL",
    "http://localhost:7860/auth/callback",
)
GITHUB_OAUTH_ENABLED = bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)

# PAT para git push + gh pr create + descubrimiento de repos (modo directo, sin OAuth).
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ACTOR = os.getenv("GITHUB_ACTOR", "")

# ── IX-1: Multi-usuario RBAC ─────────────────────────────────────────────────
# Si True, todas las rutas web requieren login.
# El primer arranque con RBAC_ENABLED=true migra el usuario de BasicAuth como owner.
RBAC_ENABLED = os.getenv("RBAC_ENABLED", "false").lower() == "true"

# ── IX-2: PWA / Push Notifications ───────────────────────────────────────────
# Claves VAPID para Web Push (opcional — solo para notificaciones push reales).
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY",  "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT     = os.getenv("VAPID_SUBJECT",     "mailto:admin@fabrica.local")

# ── Bloque VI: Paralelismo de Features ───────────────────────────────────────
# PARALLEL_FEATURES_ENABLED: si True, el Project Loop ejecuta features
# independientes en paralelo (requiere pipeline estable, error rate < 10%).
PARALLEL_FEATURES_ENABLED = os.getenv("PARALLEL_FEATURES_ENABLED", "false").lower() == "true"
MAX_PARALLEL_FEATURES     = int(os.getenv("MAX_PARALLEL_FEATURES", "2"))
# CTF-FABRICA-001: cada feature paralelo corre en su propio git worktree (checkout aislado)
# para que dos A10 concurrentes no se pisen. Si falla la creación → fallback a repo compartido.
PARALLEL_WORKTREE_ISOLATION = os.getenv("PARALLEL_WORKTREE_ISOLATION", "true").lower() == "true"

# ── Bloque III: Reducción de Intervención Humana ──────────────────────────────
# Ventana de veto: minutos que el Founder tiene para vetar un plan antes de que
# el pipeline continúe automáticamente (solo aplica en project_mode).
VETO_WINDOW_MINUTES = int(os.getenv("VETO_WINDOW_MINUTES", "30"))

# Auto-merge: si True y risk_level=LOW, el PR se fusiona automáticamente tras crearse.
# F1.5: además exige que el gate de cierre (sandbox + seguridad) esté verde; si no,
# el auto-merge se bloquea aunque risk_level sea LOW.
AUTO_MERGE_ENABLED = os.getenv("AUTO_MERGE_ENABLED", "false").lower() == "true"

# ── Bloque C (PLAN_BLINDAJE_TOTAL): condición de auto-merge ampliada ───────────
# C3: el revisor independiente (una GitHub Action que corre FUERA de este pipeline)
# también debe estar verde antes del auto-merge. Esta flag documenta y expone ese
# requisito para que el workflow de CI y a1_pr_final puedan consultarlo. El gate real
# se aplica vía is_auto_mergeable(independent_review_passed=...). Default seguro: true.
INDEPENDENT_REVIEW_REQUIRED = os.getenv("INDEPENDENT_REVIEW_REQUIRED", "true").lower() == "true"

# ── Fase 1 (PLAN_HARDENING_FABRICA): endurecimiento de gates ──────────────────
# STRICT_GATES: si True, una herramienta requerida-por-stack ausente cuenta como
# FALLO del gate (no skip silencioso). Espejo leído también por tools/code_sandbox.py.
STRICT_GATES = os.getenv("STRICT_GATES", "true").lower() == "true"
# TENANT_ISOLATION_GATE: "auto" (activo si el repo destino es Django y usa id_empresa),
# "true" (forzar), "false" (desactivar). Gate DURO de aislamiento multi-tenant (R-CODE-1).
TENANT_ISOLATION_GATE = os.getenv("TENANT_ISOLATION_GATE", "auto").lower()

# ── Fase 2 (PLAN_HARDENING): A8.5 revisión adversarial a nivel repo ───────────
# Agente adversarial que revisa el REPO COMPLETO (no el snippet del state) buscando
# fugas cross-tenant / endpoints duplicados inseguros (punto ciego de CRIT-1..3).
ADVERSARIAL_REVIEW_ENABLED = os.getenv("ADVERSARIAL_REVIEW_ENABLED", "true").lower() == "true"
# Iteraciones A8.5→A6 antes de escalar a humano.
MAX_ADVERSARIAL_ITER = int(os.getenv("MAX_ADVERSARIAL_ITER", "2"))
# Tier mínimo para correr el análisis LLM completo (el escaneo estático corre siempre).
# Valores: LOW | MEDIUM | HIGH. Por defecto MEDIUM (LOW solo recibe el escaneo estático).
ADVERSARIAL_MIN_TIER = os.getenv("ADVERSARIAL_MIN_TIER", "MEDIUM").upper()
MODEL_A85 = os.getenv("MODEL_A85", MODEL_A8)   # mismo modelo que SecOps por defecto

# ── PLAN_BLINDAJE_TOTAL — Bloque A: hardening de seguridad de la fábrica ──────
# A1.1 — Whitelist de administradores de Telegram. Lista de user IDs (no chat_id)
# autorizados a enviar comandos / pulsar botones. Vacío = compatibilidad hacia atrás
# (solo se valida chat_id, con advertencia en logs). Recomendado: definirlo en prod.
TELEGRAM_ADMIN_IDS_RAW = os.getenv("TELEGRAM_ADMIN_IDS", "")


def parse_admin_ids() -> set[int]:
    """Parsea TELEGRAM_ADMIN_IDS (lista separada por comas) → set[int]."""
    out: set[int] = set()
    for tok in (TELEGRAM_ADMIN_IDS_RAW or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.add(int(tok))
        except ValueError:
            continue
    return out


TELEGRAM_ADMIN_IDS = parse_admin_ids()

# A1.2 — Autenticación obligatoria de la UI. Si no hay RBAC ni Basic Auth configurada,
# la UI se niega a arrancar (fallo seguro). Poner UI_ALLOW_NO_AUTH=true SOLO en
# desarrollo local consciente (la UI quedaría abierta a quien tenga acceso de red).
UI_ALLOW_NO_AUTH = os.getenv("UI_ALLOW_NO_AUTH", "false").lower() == "true"

# A2.2 — Scanner determinista de secretos como gate duro en A9. Si encuentra un secreto
# en los archivos generados, el gate FALLA (no depende de que el LLM de A8 lo note).
SECRET_SCAN_GATE = os.getenv("SECRET_SCAN_GATE", "true").lower() == "true"

# R4 (PLAN_PLATAFORMA_V2 Fase 1) — Validador de input (AIDefence lite) antes de A0.
# INPUT_VALIDATION_GATE: si true, el brief se valida (inyección de prompt → bloqueo;
# PII/secretos → sanitización). INPUT_VALIDATION_STRICT: PII/secretos también bloquean.
INPUT_VALIDATION_GATE   = os.getenv("INPUT_VALIDATION_GATE", "true").lower() == "true"
INPUT_VALIDATION_STRICT = os.getenv("INPUT_VALIDATION_STRICT", "false").lower() == "true"

# M4 (PLAN_PLATAFORMA_V2 Fase 1) — Diff inteligente en A6. Mide cuánto reescribió A6
# el código (ratio entrada↔salida); si supera el umbral, escala (sobre-refactor).
# Opt-in: observacional por defecto (registra el ratio); el aviso solo dispara con gate on.
INTELLIGENT_DIFF_GATE      = os.getenv("INTELLIGENT_DIFF_GATE", "false").lower() == "true"
INTELLIGENT_DIFF_THRESHOLD = float(os.getenv("INTELLIGENT_DIFF_THRESHOLD", "0.85"))

# M3 (PLAN_PLATAFORMA_V2 Fase 1) — LLM-as-judge: evaluador ligero puntúa la salida de
# cada agente (post_agent). Opt-in (añade ~1 llamada LLM barata por agente). Por debajo
# de LLM_JUDGE_MIN_SCORE se registra/escala. Default off → comportamiento idéntico.
LLM_JUDGE_ENABLED   = os.getenv("LLM_JUDGE_ENABLED", "false").lower() == "true"
LLM_JUDGE_MODEL     = os.getenv("LLM_JUDGE_MODEL", MODEL_FAST)
LLM_JUDGE_MIN_SCORE = int(os.getenv("LLM_JUDGE_MIN_SCORE", "60"))

# M5 (PLAN_PLATAFORMA_V2 Fase 2) — Caché local de prompts para proveedores sin caché
# nativa (Anthropic ya cachea → se salta). Opt-in; default off → comportamiento idéntico.
SEMANTIC_CACHE_ENABLED     = os.getenv("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
SEMANTIC_CACHE_TTL_SECONDS = int(os.getenv("SEMANTIC_CACHE_TTL_SECONDS", "86400"))

# M8 (PLAN_PLATAFORMA_V2 Fase 2) — Contexto dinámico: en A0 (continuar proyecto),
# añade los archivos más relevantes a la tarea por keywords, además del snapshot.
# Opt-in; default off → comportamiento idéntico.
DYNAMIC_CONTEXT_ENABLED = os.getenv("DYNAMIC_CONTEXT_ENABLED", "false").lower() == "true"

# R1 (PLAN_PLATAFORMA_V2 Fase 2) — Memoria vectorial. Si está habilitado Y chromadb
# instalado → búsqueda semántica; si no, fallback por keywords sobre JSONL. La fábrica
# NO requiere chromadb (dependencia opcional: `pip install chromadb`). Default off.
VECTOR_MEMORY_ENABLED = os.getenv("VECTOR_MEMORY_ENABLED", "false").lower() == "true"

# M6 (PLAN_PLATAFORMA_V2 Fase 3) — A/B testing de modelos por agente. En AB_TESTING_PCT
# de los features, el agente usa su modelo alternativo (model_fallbacks del registry) y se
# registra el resultado para recomendar el óptimo por rol. Opt-in; default off → idéntico.
AB_TESTING_ENABLED = os.getenv("AB_TESTING_ENABLED", "false").lower() == "true"
AB_TESTING_PCT     = float(os.getenv("AB_TESTING_PCT", "0.2"))

# R3 (PLAN_PLATAFORMA_V2 Fase 2) — Paralelismo INTRA-feature A4+A5. Cuando ambos agentes
# están activos (no skip), corren concurrentes (ThreadPoolExecutor con contexto aislado por
# hilo) y A6 unifica. Opt-in; default off → ruta secuencial idéntica. NO confundir con
# PARALLEL_FEATURES_ENABLED (paralelismo a nivel feature, escalado a CTF-FABRICA-001, intocado).
PARALLEL_AGENTS_ENABLED = os.getenv("PARALLEL_AGENTS_ENABLED", "false").lower() == "true"

# Fase 5 (PLAN_PLATAFORMA_V2) — Agent Builder. Permite REGISTRAR agentes generados
# conversacionalmente en el registry. Default off + aprobación explícita del fundador por
# registro (doble gate): la fábrica no se auto-modifica sin intención humana.
AGENT_BUILDER_ENABLED = os.getenv("AGENT_BUILDER_ENABLED", "false").lower() == "true"

# Fase 6 (PLAN_PLATAFORMA_V2) — Pipeline Builder. Permite ESCRIBIR pipelines generados
# conversacionalmente (pipelines/<name>/pipeline.yaml). Mismo doble gate que Agent Builder.
PIPELINE_BUILDER_ENABLED = os.getenv("PIPELINE_BUILDER_ENABLED", "false").lower() == "true"

# M7 (PLAN_PLATAFORMA_V2 Fase 3) — Observabilidad OpenTelemetry. Spans por agente
# (reusa trace_id de E1.1), export OTLP a Jaeger/Tempo si OTEL_EXPORTER_OTLP_ENDPOINT.
# Opt-in; la fábrica NO requiere opentelemetry (dep opcional). Default off → no-op.
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"

# A2.3 — CORS explícito. Allowlist de orígenes (separados por comas). Vacío = no se
# añade middleware CORS (comportamiento por defecto: sin orígenes cruzados permitidos).
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# A3.4 — Validación de sesiones importadas. Los features que entran por session_importer
# se marcan source=imported y requieren aprobación explícita del Founder antes de que
# A0 los procese (mitiga prompt injection vía .md subido). Default seguro: true.
IMPORTED_SESSION_REQUIRES_APPROVAL = (
    os.getenv("IMPORTED_SESSION_REQUIRES_APPROVAL", "true").lower() == "true"
)

# ── PLAN_BLINDAJE_TOTAL — Bloque B: calidad de tests + cobertura de código nuevo ─
# B2.3 — Validación AST de los tests generados. Si un test generado no tiene asserts,
# solo asserts triviales (assert True/1/"...") o está vacío, el gate DURO `test-quality`
# FALLA y el sandbox enruta de vuelta a A7/A6 con feedback quirúrgico.
TEST_QUALITY_GATE = os.getenv("TEST_QUALITY_GATE", "true").lower() == "true"
# B2.2 — Cobertura mínima sobre el código NUEVO (líneas en files_written). Default False
# para no romper repos sin setup de coverage: si no hay datos de cobertura, el gate hace
# SKIP (n/a), nunca asume verde. COVERAGE_MIN_NEW: umbral de % por archivo nuevo.
NEW_CODE_COVERAGE_GATE = os.getenv("NEW_CODE_COVERAGE_GATE", "false").lower() == "true"
COVERAGE_MIN_NEW = int(os.getenv("COVERAGE_MIN_NEW", "80"))

# ── PLAN_BLINDAJE_TOTAL — Bloque D: entornos efímeros por feature (D1.1/D1.3) ──
# D1.1 — Orquestación de un entorno docker-compose aislado por feature (app + db +
# redis opcional) con teardown garantizado. Pesado: DESACTIVADO por defecto.
EPHEMERAL_ENV_ENABLED = os.getenv("EPHEMERAL_ENV_ENABLED", "false").lower() == "true"
# D1.3 — Límites de recursos por servicio del entorno efímero (defensa anti-fuga).
EPHEMERAL_MEM_LIMIT   = os.getenv("EPHEMERAL_MEM_LIMIT", "1g")
EPHEMERAL_CPUS        = os.getenv("EPHEMERAL_CPUS", "1.0")
# Timeout (s) del `compose up --wait`; ante timeout → teardown + fallo (no cuelga).
EPHEMERAL_TIMEOUT_SECONDS = int(os.getenv("EPHEMERAL_TIMEOUT_SECONDS", "300"))
# Antigüedad máxima (s) antes de que el reaper coseche un entorno huérfano.
EPHEMERAL_MAX_AGE_SECONDS = int(os.getenv("EPHEMERAL_MAX_AGE_SECONDS", "3600"))

# ── PLAN_BLINDAJE_TOTAL — Bloque E: resiliencia LLM (E2) ──────────────────────
# E2.1 — Backoff exponencial + manejo de 429. Reintentos máximos y delay base
# (segundos) usados por el backoff exponencial (base * 2**intento, con tope y jitter).
LLM_MAX_RETRIES          = int(os.getenv("LLM_MAX_RETRIES", "4"))
LLM_BACKOFF_BASE_SECONDS = float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "2"))
# E2.2 — Circuit breaker: fallos consecutivos del proveedor antes de ABRIR el
# breaker (fallo rápido + notificación) en lugar de dejar caer 100 features en cascada.
LLM_BREAKER_THRESHOLD    = int(os.getenv("LLM_BREAKER_THRESHOLD", "5"))
# E2.2 — Fallback de modelo: JSON opcional primario→alterno, p.ej.
# {"glm-5.1":"claude-sonnet-4-6"}. Vacío = sin fallback (comportamiento actual).
MODEL_FALLBACKS          = os.getenv("MODEL_FALLBACKS", "")


def parse_model_fallbacks() -> dict[str, str]:
    """Parsea MODEL_FALLBACKS (JSON primario→alterno) → dict. Vacío/inválido → {}."""
    import json as _json
    raw = (MODEL_FALLBACKS or "").strip()
    if not raw:
        return {}
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


# E4 — Evals deterministas del pipeline mismo: suite offline que verifica que los
# gates deterministas (secret-scan, tenant-scan, test-quality, clasificador de riesgo)
# atrapan problemas sembrados. Si False, el orquestador NO debe auto-correr la suite;
# las funciones en tools/evals.py siguen funcionando si se invocan a mano.
EVALS_ENABLED = os.getenv("EVALS_ENABLED", "true").lower() == "true"


# ── Agente de Noticias (independiente de la Fábrica) ─────────────────────────
NEWS_AGENT_ENABLED = os.getenv("NEWS_AGENT_ENABLED", "true").lower() == "true"
NEWS_AGENT_HOUR    = int(os.getenv("NEWS_AGENT_HOUR", "8"))
NEWS_AGENT_MODEL   = os.getenv("NEWS_AGENT_MODEL",   "claude-haiku-4-5-20251001")

# ── URLs OpenAI-compatibles por proveedor ─────────────────────────────────────
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "zhipu":  "https://api.z.ai/api/paas/v4/",
    "kimi":   "https://api.moonshot.ai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",   # Nemotron — OpenAI-compatible
}

# ── Proveedores IA personalizados (OpenAI-compatible) ─────────────────────────
# Cargados desde data/custom_providers.json en tiempo de arranque.
# Clave en PROVIDER_URLS: "cp_<API_KEY_VAR>"  (ej: "cp_OPENROUTER_API_KEY")
_CUSTOM_PROVIDERS_PATH = FABRICA_DIR / "data" / "custom_providers.json"

def _load_custom_providers() -> list[dict]:
    try:
        import json as _j
        if _CUSTOM_PROVIDERS_PATH.exists():
            return _j.loads(_CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8")) or []
    except Exception:
        pass
    return []

CUSTOM_PROVIDERS: list[dict] = _load_custom_providers()

for _cp in CUSTOM_PROVIDERS:
    _cp_key = "cp_" + (_cp.get("api_key_var") or "CUSTOM_API_KEY")
    if _cp.get("base_url"):
        PROVIDER_URLS[_cp_key] = _cp["base_url"]

# ── Precios ($/1M tokens) ─────────────────────────────────────────────────────
PRICES = {
    # Anthropic
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  0.80, "output":  4.00, "cache_read": 0.08},
    # Google
    "gemini-3.5-flash":          {"input":  0.30, "output":  2.50, "cache_read": 0.00},
    "gemini-2.5-flash-lite":     {"input":  0.10, "output":  0.40, "cache_read": 0.00},
    "gemini-2.5-flash":          {"input":  0.30, "output":  2.50, "cache_read": 0.00},
    "gemini-3.1-pro-preview":    {"input":  2.50, "output": 15.00, "cache_read": 0.00},
    "gemini-2.5-pro":            {"input":  1.25, "output": 10.00, "cache_read": 0.00},
    # OpenAI
    "gpt-5.5":                   {"input":  5.00, "output": 30.00, "cache_read": 0.50},
    "gpt-5.5-2026-04-23":        {"input":  5.00, "output": 30.00, "cache_read": 0.50},
    "gpt-4o":                    {"input":  2.50, "output": 10.00, "cache_read": 0.00},
    "gpt-4o-mini":               {"input":  0.15, "output":  0.60, "cache_read": 0.00},
    "gpt-4-turbo":               {"input": 10.00, "output": 30.00, "cache_read": 0.00},
    # Z.ai (ZhiPu)
    "glm-5.1":                   {"input":  0.50, "output":  1.50, "cache_read": 0.00},
    "glm-4-plus":                {"input":  0.70, "output":  2.00, "cache_read": 0.00},
    # Kimi (Moonshot)
    "kimi-k2.6":                 {"input":  1.00, "output":  3.00, "cache_read": 0.00},
    "moonshot-v1-8k":            {"input":  0.12, "output":  0.12, "cache_read": 0.00},
    "moonshot-v1-32k":           {"input":  0.24, "output":  0.24, "cache_read": 0.00},
}

_DEFAULT_PRICE = {"input": 3.00, "output": 15.00, "cache_read": 0.00}


def get_price(model: str) -> dict:
    return PRICES.get(model, _DEFAULT_PRICE)


# ── Docs estáticos por repo (leídos en runtime desde el repo destino) ─────────
STATIC_DOC_PATHS = {
    "project_context":  "agents/PROJECT_CONTEXT.md",
    "coding_standards": "agents/CODING_STANDARDS.md",
    "decision_log":     "agents/DECISION_LOG.md",
}

SYSTEM_PROMPT_PATHS = {
    "a1_pm":       "agents/agent_01_pm/system_prompt.md",
    "a2_db":       "agents/agent_02_db/system_prompt.md",
    "a3_mcp":      "agents/agent_03_mcp_toolsmith/system_prompt.md",
    "a4_backend":  "agents/agent_04_backend/system_prompt.md",
    "a5_frontend": "agents/agent_05_frontend/system_prompt.md",
    "a6_refactor": "agents/agent_06_refactor/system_prompt.md",
    "a7_qa":       "agents/agent_07_qa/system_prompt.md",
    "a8_secops":   "agents/agent_08_secops/system_prompt.md",
}
