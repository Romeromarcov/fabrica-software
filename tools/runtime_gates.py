"""
Gates de RUNTIME (PLAN_BLINDAJE_TOTAL — Bloque B).

A diferencia de tools/code_sandbox.py (gates estáticos / análisis sin levantar nada),
estos gates ejercitan el sistema EN EJECUCIÓN REAL:

  • B2.1 — `migrate` real: corre `makemigrations --check --dry-run` y luego
    `migrate --noinput` contra una base de datos REAL (Postgres en CI). Si la
    migración falla, o si manage.py / la herramienta no existe, el gate FALLA
    (nunca passed=True por ausencia — eso es soft-fail prohibido por F1.1).

  • B2.4 — smoke HTTP real: levanta el servidor (en CI con runserver), espera a que
    responda (wait_for_http) y hace GET a una lista de endpoints. Un 5xx o un error
    de conexión es FALLO; 401/403 cuentan como "respondió" (no crash).

Convenciones de resultado (espejo de code_sandbox._result):
  {"gate": <nombre>, "passed": bool, "stderr": <texto>, ...}

Diseño para tests offline:
  • Todo subprocess pasa por `_run` (parchear en tests).
  • Toda llamada HTTP de smoke pasa por `_http_get` (parchear en tests).
  • La espera del servidor (wait_for_http) usa `_probe` inyectable/parcheable.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Códigos HTTP que cuentan como "el servidor respondió" (no crash) en el smoke.
# 401/403 son respuestas legítimas (auth requerida), no fallos del servidor.
DEFAULT_EXPECTED = (200, 201, 301, 302, 401, 403)


# ── Helpers de subprocess (parcheables en tests) ──────────────────────────────

def _run(cmd: list[str], cwd: str, *, env: dict[str, str] | None = None,
         timeout: int = 120) -> tuple[int, str]:
    """Ejecuta un comando y devuelve (returncode, salida_combinada).

    returncode = -1 indica que el proceso no pudo siquiera arrancar (tool ausente,
    timeout, error de SO). El distintivo entre rc!=0 y rc==-1 lo usa el caller para
    no confundir "falló la migración" con "la herramienta no existe".
    """
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout}s): {' '.join(cmd)}"
    except (subprocess.SubprocessError, OSError) as e:
        # OSError cubre FileNotFoundError (manage.py / python ausente).
        return -1, f"No se pudo ejecutar {' '.join(cmd)}: {e}"


def run_django_migrate(project_dir: str, *, database_url: str | None = None,
                       timeout: int = 120) -> dict:
    """B2.1 — migración REAL contra la base de datos configurada.

    Corre, en `project_dir` y con DATABASE_URL en el entorno:
      1) `python manage.py makemigrations --check --dry-run`  (drift de migraciones)
      2) `python manage.py migrate --noinput`                 (aplica el esquema real)

    Reglas (F1.1, sin soft-fail):
      • Si no existe `manage.py` en project_dir → FALLA (no skip-as-pass).
      • Si cualquiera de los dos comandos no arranca (rc==-1) o devuelve rc!=0 → FALLA.

    Devuelve {"gate": "migrate-real", "passed": bool, "stderr": str}.
    """
    gate = "migrate-real"
    proj = Path(project_dir)
    manage = proj / "manage.py"
    if not manage.is_file():
        return {"gate": gate, "passed": False,
                "stderr": f"manage.py no encontrado en {project_dir} — "
                          f"no se puede verificar la migración (FALLA, no skip)."}

    env = dict(os.environ)
    if database_url:
        env["DATABASE_URL"] = database_url

    # 1) Drift de migraciones: el modelo no debe tener cambios sin migración generada.
    rc, out = _run(["python", "manage.py", "makemigrations", "--check", "--dry-run"],
                   project_dir, env=env, timeout=timeout)
    if rc != 0:
        reason = "no se pudo ejecutar" if rc == -1 else "drift detectado"
        return {"gate": gate, "passed": False,
                "stderr": f"makemigrations --check --dry-run ({reason}):\n{out[:2000]}"}

    # 2) Migración real contra la DB.
    rc, out = _run(["python", "manage.py", "migrate", "--noinput"],
                   project_dir, env=env, timeout=timeout)
    if rc != 0:
        reason = "no se pudo ejecutar" if rc == -1 else f"rc={rc}"
        return {"gate": gate, "passed": False,
                "stderr": f"migrate --noinput falló ({reason}):\n{out[:2000]}"}

    return {"gate": gate, "passed": True, "stderr": out[:2000]}


# ── Helpers HTTP (parcheables en tests) ────────────────────────────────────────

def _http_get(url: str, *, timeout: float = 10) -> int:
    """GET aislado para que los tests lo parcheen. Devuelve el status code.

    Importa httpx perezosamente: la fábrica NO depende de httpx en runtime, solo el
    job de CI (y los tests, que parchean esta función).
    """
    import httpx
    resp = httpx.get(url, timeout=timeout, follow_redirects=False)
    return resp.status_code


def smoke_http(base_url: str, endpoints: list[str], *, timeout: float = 10,
               expected: tuple[int, ...] = DEFAULT_EXPECTED) -> dict:
    """B2.4 — smoke HTTP REAL contra un servidor levantado.

    GETea cada endpoint (resuelto contra base_url). Para cada uno:
      • status en `expected`  → respondió OK.
      • status 5xx            → FALLO (el servidor crasheó / 500 interno).
      • error de conexión     → FALLO (servidor no levantó / cayó).
      • otros 4xx no esperados → FALLO (ruta rota), salvo los de `expected` (401/403…).

    Devuelve {"gate": "smoke-http", "passed": bool,
              "results": [{"path", "status"}], "stderr": str}.
    `status` es el código HTTP, o None si hubo error de conexión.
    """
    gate = "smoke-http"
    results: list[dict] = []
    errors: list[str] = []

    base = base_url.rstrip("/")
    for ep in endpoints:
        path = ep if ep.startswith("/") else "/" + ep
        url = base + path
        try:
            status = _http_get(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — error de red/cliente = servidor no responde
            # Cualquier excepción del cliente HTTP (ConnectError, TimeoutException,
            # ReadError, etc.) significa que el servidor no respondió → FALLO.
            results.append({"path": path, "status": None})
            errors.append(f"{path}: error de conexión ({type(e).__name__}: {e})")
            logger.warning("smoke_http: %s no respondió (%s)", url, e)
            continue

        results.append({"path": path, "status": status})
        if status >= 500:
            errors.append(f"{path}: {status} (5xx — error del servidor)")
        elif status not in expected:
            errors.append(f"{path}: {status} (inesperado)")

    passed = not errors
    stderr = "" if passed else "Smoke HTTP falló:\n  " + "\n  ".join(errors)
    return {"gate": gate, "passed": passed, "results": results, "stderr": stderr}


def _probe(url: str, *, timeout: float = 2.0) -> bool:
    """Sondeo de disponibilidad (parcheable en tests).

    Devuelve True si el servidor respondió ALGO (cualquier status HTTP, incluido 4xx/5xx
    — lo que importa para "está vivo" es que el socket responda). False ante error de red.
    """
    try:
        _http_get(url, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 — todavía no levantó; seguir intentando
        return False


def wait_for_http(base_url: str, *, attempts: int = 30, delay: float = 1.0,
                  path: str = "/") -> bool:
    """Espera (poll) a que el servidor responda, hasta `attempts` intentos.

    Usado por CI tras lanzar `manage.py runserver` en background. La lógica de sondeo
    está en `_probe` (parcheable) y la espera entre intentos en `_sleep` (parcheable),
    para que los tests sean instantáneos y deterministas.

    Devuelve True en cuanto el servidor responde; False si se agotan los intentos.
    """
    base = base_url.rstrip("/")
    p = path if path.startswith("/") else "/" + path
    url = base + p
    for i in range(attempts):
        if _probe(url):
            logger.info("wait_for_http: %s respondió en el intento %d", url, i + 1)
            return True
        _sleep(delay)
    logger.warning("wait_for_http: %s no respondió tras %d intentos", url, attempts)
    return False


def _sleep(seconds: float) -> None:
    """Espera entre intentos (parcheable en tests para que no duerman de verdad)."""
    time.sleep(seconds)


# ── Invocación directa: usado por el job de CI (bloque-d.yml) ──────────────────

def _main(argv: list[str]) -> int:
    """CLI mínima para el job de CI.

    Uso:
      python -m tools.runtime_gates migrate <project_dir>
      python -m tools.runtime_gates smoke <base_url> <ep1> [ep2 ...]

    Devuelve 0 si el gate pasó, 1 si falló. La salida se imprime para el log de CI.
    """
    if len(argv) < 2:
        print("uso: python -m tools.runtime_gates <migrate|smoke> ...")
        return 2

    cmd = argv[1]
    if cmd == "migrate":
        if len(argv) < 3:
            print("uso: python -m tools.runtime_gates migrate <project_dir>")
            return 2
        res = run_django_migrate(argv[2], database_url=os.getenv("DATABASE_URL"))
        print(f"[{res['gate']}] passed={res['passed']}")
        if not res["passed"]:
            print(res["stderr"])
        return 0 if res["passed"] else 1

    if cmd == "smoke":
        if len(argv) < 4:
            print("uso: python -m tools.runtime_gates smoke <base_url> <ep1> [ep2 ...]")
            return 2
        base_url = argv[2]
        endpoints = argv[3:]
        res = smoke_http(base_url, endpoints)
        print(f"[{res['gate']}] passed={res['passed']} results={res['results']}")
        if not res["passed"]:
            print(res["stderr"])
        return 0 if res["passed"] else 1

    print(f"comando desconocido: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
