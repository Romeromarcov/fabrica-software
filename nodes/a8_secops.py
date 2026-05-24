"""
Agente 8 — SecOps.

Posición en el pipeline: A7 QA → **A8** → PR Final (o de vuelta a QA si hubo correcciones)

Comportamiento:
  • Sin vulnerabilidades → SECURITY CLEARANCE → PR Final
  • Vulnerabilidades encontradas y corregidas → SECURITY BLOCK: FIXED
      → actualiza backend_code / frontend_code con el código corregido
      → vuelve a A7 QA para retest
  • Vulnerabilidades no corregibles o máx. iteraciones alcanzado → escala humano

MAX_SECOPS_ITER (default 2): máximo de ciclos SecOps→QA antes de escalar.
"""
from __future__ import annotations
import re
import logging
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from tools.learning_memory import extract_patterns, append_to_lessons
from config import MODEL_A8, MAX_SECOPS_ITER

logger = logging.getLogger(__name__)


def _extract_corrected_section(output: str, header: str) -> str | None:
    """Extrae el bloque de código bajo '## HEADER' del output del agente."""
    pattern = rf"##\s*{re.escape(header)}\s*```[\w]*\n(.*?)```"
    m = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: sección sin fence de código
    pattern2 = rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)"
    m2 = re.search(pattern2, output, re.DOTALL | re.IGNORECASE)
    return m2.group(1).strip() if m2 else None


def a8_secops(state: FabricaState) -> dict:
    """Único pase de seguridad — después de que QA pasa."""
    iteration      = state.get("secops_iterations", 0) + 1
    is_retest      = state.get("secops_iterations", 0) > 0
    retest_context = ""
    if is_retest:
        retest_context = (
            f"\n⚠️  RETEST (iteración {iteration}/{MAX_SECOPS_ITER}):\n"
            f"En la revisión anterior aplicaste correcciones. QA las probó y "
            f"puede haber reportado nuevos hallazgos. Verifica que las "
            f"vulnerabilidades previas estén realmente resueltas.\n"
        )

    task = f"""
Eres el Agente 8 — SecOps. Revisas el código implementado en busca de
vulnerabilidades de seguridad y las corriges directamente.
{retest_context}
MASTER_PLAN (contexto del feature):
---
{state['master_plan']}
---

BACKEND (Agente 4 / últimas correcciones):
---
{state.get('backend_code', 'No disponible')}
---

FRONTEND (Agente 5 / últimas correcciones):
---
{state.get('frontend_code', 'No disponible')}
---

MCP TOOLS (Agente 3):
---
{state.get('mcp_tools', 'No aplica') or 'No aplica'}
---

ÚLTIMO REPORTE QA:
---
{state.get('qa_report', 'Sin reporte QA') or 'Sin reporte QA'}
---

## TU TAREA

**PASO 1 — AUDITORÍA DE SEGURIDAD**

Revisa OWASP Top 10 enfocado en este stack:
- A01 Broken Access Control: `get_queryset()` sin filtro de `id_empresa`, endpoints sin permiso
- A02 Cryptographic Failures: secrets en código, hashing débil, sin TLS
- A03 Injection: SQL injection, command injection, XSS (`dangerouslySetInnerHTML`)
- A05 Security Misconfiguration: DEBUG=True, CORS abierto, headers inseguros
- A07 Identification/Auth failures: endpoints sin autenticación JWT
- Multi-tenant: datos de una empresa accesibles desde otra

Para cada vulnerabilidad encontrada clasifica:
  `CRÍTICA | ALTA | MEDIA | BAJA`

**PASO 2 — CORRECCIÓN (solo si hay vulnerabilidades CRÍTICA o ALTA)**

Si encuentras vulnerabilidades CRÍTICA o ALTA:
1. Corrige el código directamente
2. Entrega el código corregido completo bajo estas secciones:

## CÓDIGO BACKEND CORREGIDO
```python
[código backend completo con las correcciones aplicadas]
```

## CÓDIGO FRONTEND CORREGIDO
```typescript
[código frontend completo con las correcciones aplicadas]
```

Si solo el backend tiene cambios, omite la sección de frontend (y viceversa).
Si ninguna capa necesita cambios de código, omite ambas secciones.

**PASO 3 — VEREDICTO FINAL**

La última línea DEBE ser exactamente una de:
- `SECURITY CLEARANCE` — sin vulnerabilidades CRÍTICA/ALTA (o solo MEDIA/BAJA documentadas)
- `SECURITY BLOCK: FIXED` — había vulnerabilidades CRÍTICA/ALTA y las corregiste
- `SECURITY BLOCK: UNFIXABLE` — hay vulnerabilidades que no pueden corregirse en código
  (requieren cambio de arquitectura, secretos externos, configuración de infraestructura)
"""
    output, cost = call_agent(
        agent_key="a8_secops",
        agent_label=f"Agente 8 SecOps (iter {iteration})",
        task_content=task,
        model=MODEL_A8,
        include_static=["decision_log"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], f"a8_secops_iter{iteration}", output)

    upper = output.upper()
    cleared    = "SECURITY CLEARANCE"    in upper
    fixed      = "SECURITY BLOCK: FIXED" in upper
    unfixable  = "SECURITY BLOCK: UNFIXABLE" in upper

    # Por defecto: si no reconoce el token, ser conservador
    if not cleared and not fixed and not unfixable:
        logger.warning("A8: output sin token de veredicto — tratando como UNFIXABLE")
        unfixable = True

    # Extraer código corregido si aplica
    new_backend  = _extract_corrected_section(output, "CÓDIGO BACKEND CORREGIDO")
    new_frontend = _extract_corrected_section(output, "CÓDIGO FRONTEND CORREGIDO")

    block_msg = None if cleared else output[:600]

    logger.info(
        "A8 SecOps iter %d: clearance=%s fixed=%s unfixable=%s | "
        "backend_patch=%s frontend_patch=%s",
        iteration, cleared, fixed, unfixable,
        bool(new_backend), bool(new_frontend),
    )

    result: dict = {
        "security_clearance_2": cleared,
        "security_block_2":     block_msg,
        "secops_iterations":    iteration,
        "current_agent":        "a8_secops",
        "cost_entries":         [cost],
    }

    # Actualizar código con correcciones de seguridad
    if new_backend:
        result["backend_code"] = new_backend
    if new_frontend:
        result["frontend_code"] = new_frontend

    if unfixable:
        result["errors"] = ["SecOps: vulnerabilidad no corregible en código — requiere intervención humana"]

    # ── Sistema de aprendizaje: extraer vulnerabilidades críticas/altas ───────
    if not cleared and state["repo_path"]:
        sec_patterns = extract_patterns(
            qa_report="",
            secops_report=output,
            feature_name=state.get("feature_name", ""),
        )
        if sec_patterns:
            append_to_lessons(state["repo_path"], sec_patterns)

    return result
