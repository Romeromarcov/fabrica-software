"""
tools/post_deploy.py — Smoke post-deploy + rollback en un comando (PLAN_BLINDAJE_TOTAL D3.3).

Núcleo PURO y OFFLINE-VERIFICABLE del chequeo post-deploy:

  1. **Smoke automático** — un conjunto de checks declarativos (`SmokeCheck`) contra
     la app recién promovida. La EJECUCIÓN HTTP es la arista de infra; aquí se
     EVALÚA el resultado de cada check (`evaluate_check`) y se agrega un veredicto
     global (`evaluate_smoke`).
  2. **Alerta Telegram en fallo** — `build_smoke_alert` arma el mensaje listo para
     `telegram_bot._tg_send`, con el comando exacto de rollback.
  3. **Rollback en un comando** — reusa `deploy_release.build_rollback_plan` (D3.2):
     redeploy del tag de release anterior.

El disparo del smoke (httpx contra el endpoint vivo) y el envío real del mensaje a
Telegram requieren red/credenciales y viven fuera de este módulo. Aquí solo se
decide, dado el resultado del smoke, si hay que alertar y a qué tag volver.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tools.deploy_release import build_rollback_plan


@dataclass
class SmokeCheck:
    """Un check declarativo del smoke post-deploy."""

    name: str
    path: str
    expect_status: int = 200
    expect_contains: Optional[str] = None


def default_smoke_checks() -> list[SmokeCheck]:
    """Checks mínimos por defecto: salud del servicio y home accesible."""
    return [
        SmokeCheck(name="healthz", path="/healthz", expect_status=200),
        SmokeCheck(name="home", path="/", expect_status=200),
    ]


def evaluate_check(
    check: SmokeCheck, status_code: int, body: str = ""
) -> dict:
    """Evalúa un check contra un resultado HTTP ya obtenido (status + body).

    Pura: no hace red. Returns {"name", "ok", "detail"}.
    """
    if status_code != check.expect_status:
        return {
            "name": check.name,
            "ok": False,
            "detail": f"status {status_code} ≠ esperado {check.expect_status} ({check.path})",
        }
    if check.expect_contains and check.expect_contains not in (body or ""):
        return {
            "name": check.name,
            "ok": False,
            "detail": f"cuerpo no contiene {check.expect_contains!r} ({check.path})",
        }
    return {"name": check.name, "ok": True, "detail": f"OK ({check.path})"}


def evaluate_smoke(results: list[dict]) -> dict:
    """Agrega los resultados de los checks en un veredicto global.

    `results` es una lista de dicts {"name","ok","detail"} (cada uno de
    `evaluate_check`). Returns {"passed", "total", "failed", "failed_checks"}.
    """
    total = len(results)
    failed = [r for r in results if not r.get("ok")]
    return {
        "passed": total > 0 and not failed,
        "total": total,
        "failed": len(failed),
        "failed_checks": failed,
    }


def build_smoke_alert(deploy_tag: str, smoke: dict, rollback: dict) -> str:
    """Arma el mensaje de alerta Telegram para un smoke fallido, con el rollback.

    Devuelve "" si el smoke pasó (no hay nada que alertar).
    """
    if smoke.get("passed"):
        return ""
    lines = [
        f"🚨 Smoke post-deploy FALLÓ — {deploy_tag}",
        f"Checks fallidos: {smoke['failed']}/{smoke['total']}",
        "",
    ]
    for fc in smoke.get("failed_checks", []):
        lines.append(f"  ✗ {fc['name']}: {fc['detail']}")
    lines.append("")
    if rollback.get("can_rollback"):
        lines.append(f"↩️ Rollback en un comando → {rollback['target_tag']}:")
        lines.append(f"`{rollback['command']}`")
    else:
        lines.append("⚠️ No hay tag de release anterior: rollback manual requerido.")
    return "\n".join(lines)


def post_deploy_decision(
    *,
    deploy_tag: str,
    results: list[dict],
    existing_tags: list[str],
    current_tag: Optional[str] = None,
) -> dict:
    """Orquesta la decisión post-deploy (pura): evalúa el smoke y, si falla, arma
    el plan de rollback y la alerta.

    Returns {"ok", "smoke", "rollback", "alert"}. `ok` = el smoke pasó.
    """
    smoke = evaluate_smoke(results)
    if smoke["passed"]:
        return {"ok": True, "smoke": smoke, "rollback": None, "alert": ""}
    rollback = build_rollback_plan(existing_tags, current_tag)
    alert = build_smoke_alert(deploy_tag, smoke, rollback)
    return {"ok": False, "smoke": smoke, "rollback": rollback, "alert": alert}
