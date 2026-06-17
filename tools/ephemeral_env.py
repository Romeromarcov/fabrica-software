"""
PLAN_BLINDAJE_TOTAL — Bloque D: entornos efímeros por feature (D1.1 + D1.3).

Orquestador puro-Python que levanta un entorno docker-compose aislado por feature
(app + postgres + redis opcional), con límites de recursos (D1.3), y garantiza su
destrucción. NO hay daemon docker en este entorno de fábrica: TODA interacción con
docker pasa por subprocess a través de un único helper privado `_run`, de modo que
el módulo es completamente unit-testeable parcheando `_run` (mismo patrón que
railway_client / worktree / code_sandbox).

Diseño:
  • Funciones puras (sin docker): `project_name`, `compose_config`, `compose_yaml`,
    `select_orphans`. Unit-testeables sin red ni daemon.
  • Funciones con efectos: `create_ephemeral_env`, `destroy_ephemeral_env`,
    `ephemeral_env` (context manager con teardown garantizado), `reap_orphans`.
  • Toda llamada larga de `_run` lleva timeout; ante TimeoutExpired → teardown +
    fallo (sin colgarse).
  • Sin except desnudo: se capturan SubprocessError, OSError y TimeoutExpired.
  • Sin efectos secundarios al importar; reloj inyectable (`now`) para el reaper.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import tempfile
import time

import yaml

logger = logging.getLogger(__name__)

# Prefijo común de todos los proyectos efímeros (para descubrirlos/cosecharlos).
PROJECT_PREFIX = "fab-eph-"

# Tope de longitud del nombre de proyecto (docker-compose tolera nombres largos,
# pero acotamos para mantenerlo legible y compatible).
_MAX_PROJECT_LEN = 48


# ── Helper único de subprocess (parcheable en tests) ───────────────────────────

def _run(cmd: list[str], *, cwd: str | None = None,
         timeout: int = 120) -> tuple[str, str, int]:
    """Ejecuta `cmd` y devuelve (stdout, stderr, returncode).

    Único punto de contacto con el sistema: los tests parchean ESTA función para
    simular docker sin daemon. Propaga `subprocess.TimeoutExpired` para que el
    llamador haga teardown; convierte OSError (p.ej. binario ausente) en rc != 0.
    """
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        # Se re-lanza: el llamador decide teardown + fallo (no debe colgarse).
        raise
    except (subprocess.SubprocessError, OSError) as e:
        # Binario ausente / error de spawn: lo tratamos como fallo de ejecución.
        return "", str(e), 127


# ── Helpers de configuración (referencia dinámica → monkeypatch-friendly) ──────

def _cfg(name: str, default):
    """Lee un valor de config.py de forma dinámica (para que los tests lo parcheen)."""
    try:
        import config
        return getattr(config, name, default)
    except (ImportError, AttributeError):
        return default


# ── Funciones puras (sin docker) ───────────────────────────────────────────────

def project_name(feature_id: str) -> str:
    """Nombre de proyecto docker-compose derivado del feature_id.

    Sanitiza a `[a-z0-9-]` (minúsculas), colapsa separadores, recorta y antepone el
    prefijo común. Pura y determinista.
    """
    raw = (feature_id or "").lower()
    # Cualquier cosa que no sea [a-z0-9] → guion.
    sanitized = re.sub(r"[^a-z0-9]+", "-", raw)
    sanitized = sanitized.strip("-")
    if not sanitized:
        sanitized = "anon"
    name = PROJECT_PREFIX + sanitized
    if len(name) > _MAX_PROJECT_LEN:
        name = name[:_MAX_PROJECT_LEN].rstrip("-")
    return name


def _limits_for(limits: dict | None) -> dict:
    """Resuelve los límites de recursos (D1.3) desde `limits` o config por defecto."""
    mem = (limits or {}).get("mem_limit") or _cfg("EPHEMERAL_MEM_LIMIT", "1g")
    cpus = (limits or {}).get("cpus") or _cfg("EPHEMERAL_CPUS", "1.0")
    return {"mem_limit": str(mem), "cpus": str(cpus)}


def _service_with_limits(service: dict, lims: dict) -> dict:
    """Aplica límites de recursos a un servicio.

    Se usan las claves `mem_limit`/`cpus` (compatibles con `docker compose up` sin
    Swarm) Y `deploy.resources.limits` (espejo declarativo), de modo que el límite
    sea visible/aserrable sin importar qué runtime los consuma.
    """
    out = dict(service)
    out["mem_limit"] = lims["mem_limit"]
    out["cpus"] = lims["cpus"]
    out["deploy"] = {
        "resources": {
            "limits": {"cpus": lims["cpus"], "memory": lims["mem_limit"]},
        }
    }
    return out


def compose_config(repo_path: str, feature_id: str, *,
                   with_redis: bool = False, limits: dict | None = None) -> dict:
    """Construye el dict de docker-compose para un entorno efímero del feature.

    Servicios: `app` (build del repo) + `db` (postgres:16 con healthcheck) +
    `redis` opcional. `app` depende de `db` sano y recibe `DATABASE_URL` apuntando
    al servicio `db`. Cada servicio lleva límites de recursos (D1.3). El nombre de
    proyecto (único por feature) se incluye como `name` para evitar colisiones entre
    features concurrentes. Pura: no toca docker ni el disco.
    """
    proj = project_name(feature_id)
    lims = _limits_for(limits)

    db_user = "fab"
    db_pass = "fab"
    db_name = "fab"
    # DATABASE_URL apunta al servicio `db` por su nombre de red interno de compose.
    database_url = f"postgresql://{db_user}:{db_pass}@db:5432/{db_name}"

    db_service = _service_with_limits({
        "image": "postgres:16",
        "environment": {
            "POSTGRES_USER": db_user,
            "POSTGRES_PASSWORD": db_pass,
            "POSTGRES_DB": db_name,
        },
        # Healthcheck: `app` no arranca hasta que postgres responde.
        "healthcheck": {
            "test": ["CMD-SHELL", f"pg_isready -U {db_user} -d {db_name}"],
            "interval": "5s",
            "timeout": "5s",
            "retries": 5,
            "start_period": "10s",
        },
    }, lims)

    app_service = _service_with_limits({
        # Build del repo destino (Dockerfile en repo_path).
        "build": {"context": str(repo_path)},
        "environment": {
            "DATABASE_URL": database_url,
        },
        "depends_on": {
            "db": {"condition": "service_healthy"},
        },
    }, lims)

    services = {"app": app_service, "db": db_service}

    if with_redis:
        redis_service = _service_with_limits({
            "image": "redis:7",
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "5s",
                "timeout": "5s",
                "retries": 5,
            },
        }, lims)
        services["redis"] = redis_service
        # `app` también espera a redis sano.
        app_service["depends_on"]["redis"] = {"condition": "service_healthy"}
        app_service["environment"]["REDIS_URL"] = "redis://redis:6379/0"

    return {
        "name": proj,            # nombre de proyecto único (anti-colisión)
        "services": services,
    }


def compose_yaml(cfg: dict) -> str:
    """Serializa el dict de compose a YAML. Pura."""
    return yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False)


def select_orphans(projects: list[dict], max_age: int, now: float) -> list[str]:
    """Decide qué proyectos efímeros cosechar (pura, unit-testeable).

    `projects`: lista de {"project": str, "created": <epoch seconds>}.
    Devuelve los nombres con prefijo `fab-eph-` cuya antigüedad (now - created)
    supera `max_age`. Ignora proyectos sin prefijo o sin timestamp válido.
    """
    reap: list[str] = []
    for p in projects:
        name = p.get("project") or p.get("name") or ""
        if not name.startswith(PROJECT_PREFIX):
            continue
        created = p.get("created")
        if created is None:
            continue
        try:
            age = float(now) - float(created)
        except (TypeError, ValueError):
            continue
        if age > max_age:
            reap.append(name)
    return reap


# ── Funciones con efectos (docker vía _run) ────────────────────────────────────

def _resolve_project(feature_id_or_project: str) -> str:
    """Acepta un feature_id o un nombre de proyecto ya formado (`fab-eph-...`)."""
    if feature_id_or_project.startswith(PROJECT_PREFIX):
        return feature_id_or_project
    return project_name(feature_id_or_project)


def _write_compose_file(cfg: dict) -> str:
    """Escribe el YAML de compose a un archivo temporal y devuelve su ruta."""
    fd, path = tempfile.mkstemp(prefix="fab-eph-", suffix=".compose.yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(compose_yaml(cfg))
    return path


def destroy_ephemeral_env(feature_id_or_project: str) -> bool:
    """Destruye el entorno efímero (idempotente).

    `docker compose -p <name> down -v --remove-orphans`. Devuelve True si el comando
    salió 0 (o si no había nada que destruir). Nunca lanza: ante timeout/error de
    subprocess, loguea y devuelve False.
    """
    name = _resolve_project(feature_id_or_project)
    cmd = ["docker", "compose", "-p", name, "down", "-v", "--remove-orphans"]
    try:
        _out, err, rc = _run(cmd, timeout=120)
    except subprocess.TimeoutExpired:
        logger.warning("ephemeral: timeout destruyendo %s", name)
        return False
    if rc != 0:
        logger.warning("ephemeral: 'compose down' de %s salió %s: %s", name, rc, err[:200])
    return rc == 0


def create_ephemeral_env(repo_path: str, feature_id: str, *,
                         timeout: int | None = None,
                         with_redis: bool = False) -> dict:
    """Crea el entorno efímero del feature y lo levanta con `--wait`.

    Escribe el compose a un temporal y corre `docker compose -p <name> up -d --wait`.
    Devuelve {"project", "ok", "compose_file", "stderr"}. Ante fallo o timeout,
    intenta teardown y devuelve ok=False sin propagar excepción.
    """
    if timeout is None:
        timeout = int(_cfg("EPHEMERAL_TIMEOUT_SECONDS", 300))

    name = project_name(feature_id)
    cfg = compose_config(repo_path, feature_id, with_redis=with_redis)
    compose_file = _write_compose_file(cfg)

    cmd = ["docker", "compose", "-p", name, "-f", compose_file, "up", "-d", "--wait"]
    try:
        _out, err, rc = _run(cmd, cwd=str(repo_path), timeout=timeout)
    except subprocess.TimeoutExpired:
        # No nos colgamos: teardown y fallo explícito.
        logger.warning("ephemeral: timeout levantando %s — teardown", name)
        destroy_ephemeral_env(name)
        return {"project": name, "ok": False, "compose_file": compose_file,
                "stderr": f"timeout tras {timeout}s levantando el entorno"}

    if rc != 0:
        # Fallo de arranque: intentamos teardown para no dejar contenedores colgados.
        logger.warning("ephemeral: 'compose up' de %s salió %s — teardown", name, rc)
        destroy_ephemeral_env(name)
        return {"project": name, "ok": False, "compose_file": compose_file,
                "stderr": err[:2000]}

    return {"project": name, "ok": True, "compose_file": compose_file, "stderr": ""}


@contextlib.contextmanager
def ephemeral_env(repo_path: str, feature_id: str, **kw):
    """Context manager: crea el entorno al entrar y GARANTIZA teardown al salir.

    El teardown corre en `finally` aunque el cuerpo del `with` lance. Yielda el dict
    devuelto por `create_ephemeral_env`.
    """
    env = create_ephemeral_env(repo_path, feature_id, **kw)
    try:
        yield env
    finally:
        # Teardown garantizado, incluso si el cuerpo lanzó o la creación falló.
        destroy_ephemeral_env(env.get("project") or project_name(feature_id))


def _parse_compose_ls(stdout: str) -> list[dict]:
    """Parsea la salida JSON de `docker compose ls --format json` a [{project,...}].

    Tolera tanto un array JSON como JSON-lines (un objeto por línea). El campo de
    timestamp no es fiable en `compose ls`; el reaper lo completa con `docker inspect`
    a nivel de llamador, así que aquí solo extraemos el nombre.
    """
    import json
    projects: list[dict] = []
    text = (stdout or "").strip()
    if not text:
        return projects
    # ¿Array JSON?
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("Name"):
                    projects.append({"project": item["Name"]})
            return projects
    except (ValueError, TypeError) as e:
        # No era un array JSON: lo registramos y caemos al parseo JSON-lines.
        logger.debug("ephemeral: salida de 'compose ls' no es array JSON (%s) — pruebo JSON-lines", e)
    # JSON-lines.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and item.get("Name"):
            projects.append({"project": item["Name"]})
    return projects


def _project_created_epoch(project: str) -> float | None:
    """Antigüedad de un proyecto: timestamp de creación del contenedor más viejo.

    Usa `docker ps` filtrando por la etiqueta de proyecto de compose. Devuelve el
    epoch de creación o None si no se pudo determinar (no lo cosechamos a ciegas).
    """
    cmd = ["docker", "ps", "-a", "--no-trunc",
           "--filter", f"label=com.docker.compose.project={project}",
           "--format", "{{.CreatedAt}}"]
    try:
        out, _err, rc = _run(cmd, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if rc != 0:
        return None
    epochs: list[float] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        ep = _parse_docker_time(line)
        if ep is not None:
            epochs.append(ep)
    return min(epochs) if epochs else None


def _parse_docker_time(s: str) -> float | None:
    """Parsea un timestamp de `docker ps` (`.CreatedAt`) a epoch seconds.

    Formato típico: '2026-06-16 10:11:12 +0000 UTC'. Devuelve None si no parsea.
    """
    from datetime import datetime
    s = s.strip()
    # Quitamos el sufijo de zona textual ('UTC', 'CEST', ...) que datetime no lee.
    parts = s.split()
    # Reconstruimos 'YYYY-MM-DD HH:MM:SS +0000' (3 primeros tokens).
    candidate = " ".join(parts[:3]) if len(parts) >= 3 else s
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(candidate, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def reap_orphans(max_age_seconds: int, *, now: float | None = None) -> list[str]:
    """Cosecha entornos efímeros huérfanos más viejos que `max_age_seconds`.

    Lista proyectos con `docker compose ls`, filtra los prefijados `fab-eph-`,
    determina su antigüedad (vía `docker ps`) y destruye los caducados. `now` es
    inyectable para tests deterministas. Devuelve los nombres cosechados.
    """
    if now is None:
        now = time.time()

    cmd = ["docker", "compose", "ls", "--all", "--format", "json"]
    try:
        out, _err, rc = _run(cmd, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("ephemeral: timeout listando proyectos para cosecha")
        return []
    if rc != 0:
        return []

    listed = _parse_compose_ls(out)
    # Enriquecemos con timestamp de creación (solo para los nuestros).
    enriched: list[dict] = []
    for p in listed:
        name = p.get("project", "")
        if not name.startswith(PROJECT_PREFIX):
            continue
        created = _project_created_epoch(name)
        enriched.append({"project": name, "created": created})

    to_reap = select_orphans(enriched, max_age_seconds, now)
    reaped: list[str] = []
    for name in to_reap:
        if destroy_ephemeral_env(name):
            reaped.append(name)
    return reaped
