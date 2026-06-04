# Runbook — Operar la Fábrica sobre OmniERP (Fase 7)

Cómo arrancar, supervisar y mantener el lazo de la fábrica construyendo OmniERP con la
intervención humana mínima **sin comprometer las garantías**.

## 7.1 — Arranque

**Prerrequisitos:** entorno con `langgraph` y claves de IA (`ANTHROPIC_API_KEY`, etc.);
la fábrica corre en Docker (`docker-compose up`) o en el venv. `WORKSPACES_ROOT` apunta a
`C:\Users\PC\Proyectos` para descubrir `omni-erp`.

**Env recomendado (entrega):** ver [`ONBOARDING_OMNIERP.md`](ONBOARDING_OMNIERP.md) §5.4.
Claves: `STRICT_GATES=true`, `TENANT_ISOLATION_GATE=auto`, `ADVERSARIAL_REVIEW_ENABLED=true`,
`AUTO_MERGE_ENABLED=false`, `PARALLEL_FEATURES_ENABLED=false`.

**Onboarding (una vez):**
```bash
python cli.py project "Onboarding OmniERP" "Cerrar hallazgos criticos" --repo omni-erp --audit
```
Luego generar reconciliación y backlog crítico-primero:
```python
from tools.reconciler import reconcile, render_reconciliation
from tools.audit_backlog import build_backlog
# RECONCILIACION.md + backlog de la auditoria (CRIT/H-SEC primero, tier HIGH)
```

## 7.2 — Observabilidad

Cada feature deja en `data/runs/<feature_id>/metadata.json` las señales de gobernanza.
`tools/governance_report.feature_governance(feature_id)` las resume:
- **Riesgo:** LLM vs rutas vs efectivo vs final (se ve si el LLM intentó bajar el tier).
- **Veredictos:** seguridad (A8) y adversarial (A8.5).
- **Aprobación:** auto / veto / humano · si fue auto-mergeable.

Artefactos por feature: `SECURITY_REPORT.md`, `output_a85_adversarial_iter*.md`,
la tabla "Verificación de garantías" en el cuerpo del PR.

## 7.3 — Política de reversibilidad (red de seguridad)

- Todo merge automático usa **squash** → un solo commit revertible (`git revert`).
- Solo tier **LOW + gate verde** se auto-fusiona; todo lo demás queda en **PR draft** para
  revisión humana (el agente nunca marca "ready" — R-PROC-3 de OmniERP).
- Alineado con **R-PROD-4** de OmniERP (reversibilidad por defecto): aceptar autonomía es
  seguro porque el error es recuperable.

## 7.4 — Arranque supervisado (ramp-up de autonomía)

La autonomía se **gana**, no se asume:

1. **Semana 1–2:** `AUTO_MERGE_ENABLED=false`. Todo termina en PR draft; el humano revisa
   incluso los LOW. Objetivo: medir la tasa de **falsos-OK** (gate verde pero el humano
   habría vetado). Debe ser **cero**.
2. **Cuando falsos-OK = 0 sostenido:** activar `AUTO_MERGE_ENABLED=true`. A partir de aquí
   solo los LOW con gate verde se fusionan solos; MEDIUM avisa; HIGH siempre humano.
3. **Paralelismo:** mantener `PARALLEL_FEATURES_ENABLED=false` hasta cerrar
   [`CTF-FABRICA-001`](ctf/CTF-FABRICA-001.md) (aislamiento por worktree).

## Respuesta a interrupciones (Telegram)

- **Ventana de veto** (tier MEDIUM): responder `VETAR` para detener, o nada para aprobar.
- **Escalación** (QA/SecOps/A8.5 agotaron iteraciones, o tier HIGH): `REDISEÑAR` / `ACEPTAR`
  / `CANCELAR`.
- **Conflicto de merge HIGH**: `RESOLVER` (resolviste a mano) / `CANCELAR` (descartar ramas).
- **Pausa:** `PAUSA` en cualquier checkpoint.

## Mantenimiento

- Revisar `docs/ctf/` (compromisos fechados) y cerrarlos antes de su vencimiento.
- Re-correr la **reconciliación** tras cada bloque grande para que el plan no vuelva a
  divergir del código.
- La quincena impar es de pago de deuda (R-PROC-7 de OmniERP): refactor, tests, CTFs.
