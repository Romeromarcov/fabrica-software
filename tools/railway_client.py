"""
VII-3 — Railway Client: wrapper de la Railway API v2 (GraphQL).

Documentación: https://docs.railway.com/reference/public-api

Variables de entorno requeridas:
  RAILWAY_TOKEN      — API token (Account Settings → Tokens)
  RAILWAY_PROJECT_ID — ID del proyecto en Railway

Funciones disponibles:
  list_services()           → lista servicios del proyecto
  trigger_deploy()          → dispara un nuevo deploy
  get_deployment_status()   → estado actual de un deploy
  get_deployment_logs()     → logs en tiempo real (async generator)
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_RAILWAY_API = "https://backboard.railway.com/graphql/v2"


def _headers() -> dict[str, str]:
    token = os.getenv("RAILWAY_TOKEN", "")
    if not token:
        # Fallback: leer del ConfigStore
        try:
            from ui.config_store import ConfigStore
            cfg = ConfigStore().load(masked=False)
            token = cfg.get("RAILWAY_TOKEN", "")
        except Exception:
            pass
    if not token:
        raise ValueError("RAILWAY_TOKEN no configurado. Agrégalo en Configuración → Railway.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


def _project_id() -> str:
    pid = os.getenv("RAILWAY_PROJECT_ID", "")
    if not pid:
        try:
            from ui.config_store import ConfigStore
            cfg = ConfigStore().load(masked=False)
            pid = cfg.get("RAILWAY_PROJECT_ID", "")
        except Exception:
            pass
    if not pid:
        raise ValueError("RAILWAY_PROJECT_ID no configurado.")
    return pid


# ── Queries GraphQL ───────────────────────────────────────────────────────────

_Q_SERVICES = """
query GetServices($projectId: String!) {
  project(id: $projectId) {
    id
    name
    services {
      edges {
        node {
          id
          name
          deployments(first: 1) {
            edges {
              node {
                id
                status
                createdAt
                url
              }
            }
          }
        }
      }
    }
  }
}
"""

_Q_TRIGGER_DEPLOY = """
mutation TriggerDeploy($serviceId: String!, $environmentId: String) {
  serviceInstanceDeploy(serviceId: $serviceId, environmentId: $environmentId)
}
"""

_Q_DEPLOYMENT_STATUS = """
query DeploymentStatus($deploymentId: String!) {
  deployment(id: $deploymentId) {
    id
    status
    createdAt
    url
    staticUrl
  }
}
"""


# ── Helpers HTTP ──────────────────────────────────────────────────────────────

async def _gql(query: str, variables: dict | None = None) -> dict:
    """Ejecuta una query GraphQL en la API de Railway."""
    import httpx
    payload = {"query": query, "variables": variables or {}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(_RAILWAY_API, json=payload, headers=_headers())
        r.raise_for_status()
        data = r.json()
    if "errors" in data:
        errs = "; ".join(e.get("message", str(e)) for e in data["errors"])
        raise RuntimeError(f"Railway API error: {errs}")
    return data.get("data", {})


# ── API pública ───────────────────────────────────────────────────────────────

async def list_services() -> dict:
    """
    Lista los servicios del proyecto Railway configurado.
    Returns: {"services": [{"id", "name", "latest_deployment": {...}}]}
    """
    project_id = _project_id()
    data = await _gql(_Q_SERVICES, {"projectId": project_id})
    project = data.get("project", {})
    services = []
    for edge in project.get("services", {}).get("edges", []):
        node = edge["node"]
        deploys = node.get("deployments", {}).get("edges", [])
        latest = deploys[0]["node"] if deploys else {}
        services.append({
            "id":                node["id"],
            "name":              node["name"],
            "latest_deployment": latest,
        })
    return {
        "project_id":   project_id,
        "project_name": project.get("name", ""),
        "services":     services,
    }


async def trigger_deploy(
    service_id: str,
    environment: str = "production",
) -> dict:
    """
    Dispara un nuevo deploy para el servicio indicado.
    Returns: {"deployment_id": str, "status": "BUILDING"}
    """
    if not service_id:
        raise ValueError("service_id requerido")

    # Railway necesita el environmentId, no el nombre. Si no se pasa, usa producción.
    env_id = None
    if environment and environment != "production":
        env_id = environment   # permite pasar el ID directamente

    data = await _gql(
        _Q_TRIGGER_DEPLOY,
        {"serviceId": service_id, "environmentId": env_id},
    )

    # La mutación retorna el deploymentId directamente
    deployment_id = data.get("serviceInstanceDeploy", "")
    logger.info("railway: deploy disparado → %s", deployment_id)
    return {
        "ok":           True,
        "deployment_id": deployment_id,
        "status":       "BUILDING",
        "message":      f"Deploy iniciado para servicio {service_id}",
    }


async def get_deployment_status(deployment_id: str) -> dict:
    """
    Retorna el estado actual de un deploy.
    Returns: {"id", "status", "url", "created_at"}
    """
    if not deployment_id:
        return {"error": "deployment_id requerido"}

    data = await _gql(_Q_DEPLOYMENT_STATUS, {"deploymentId": deployment_id})
    dep = data.get("deployment", {})
    return {
        "id":         dep.get("id", ""),
        "status":     dep.get("status", "UNKNOWN"),
        "url":        dep.get("staticUrl") or dep.get("url") or "",
        "created_at": dep.get("createdAt", ""),
    }


async def stream_deployment_logs(deployment_id: str) -> AsyncIterator[str]:
    """
    Genera logs de un deploy en tiempo real via HTTP streaming.
    Yielda líneas de log como strings.
    """
    import httpx
    logs_url = f"https://backboard.railway.com/deployments/{deployment_id}/logs"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", logs_url, headers=_headers()) as r:
                async for line in r.aiter_lines():
                    if line:
                        yield line
    except Exception as exc:
        logger.warning("railway logs stream error: %s", exc)
        yield f"[Error obteniendo logs: {exc}]"
