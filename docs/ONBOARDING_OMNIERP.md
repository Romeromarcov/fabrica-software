# Onboarding de OmniERP en la Fábrica (Fase 5)

Cómo registrar OmniERP como proyecto destino y por qué los gates de la fábrica son un
**superconjunto** del Definition of Done de OmniERP.

## 5.4 — Registro del repo

| Parámetro | Valor |
|---|---|
| Ruta | `C:\Users\PC\Proyectos\omni-erp` (descubierto vía `WORKSPACES_ROOT`) |
| Stack | Django (backend) + React/TS (frontend) — autodetectado por `code_sandbox._detect_stack` |
| Comandos de gate | Espejo del CI de OmniERP: `pytest`, `makemigrations --check --dry-run`, `migrate --check`, `tsc`, `npm build`, `eslint` + **gate de aislamiento** (Fase 1.2) |
| Docs de gobernanza a inyectar | `CLAUDE.md`, `docs/DEFINITION_OF_DONE.md`, `docs/PLAN_MAESTRO_UNICO.md` (§2 reglas) |

**Variables de entorno recomendadas para OmniERP (entrega):**
```
STRICT_GATES=true
TENANT_ISOLATION_GATE=auto        # se activa solo: OmniERP es Django + id_empresa
ADVERSARIAL_REVIEW_ENABLED=true
ADVERSARIAL_MIN_TIER=MEDIUM
AUTO_MERGE_ENABLED=false          # arranque conservador (subir a true solo para tier LOW probado)
PARALLEL_FEATURES_ENABLED=false   # ver CTF-FABRICA-001 antes de activar
```

**Primer arranque (modo audit + reconciliación):**
```bash
python cli.py project "Onboarding OmniERP" "Cerrar hallazgos críticos de seguridad" \
    --repo omni-erp --audit
```
El modo `--audit` genera el contexto del repo; sobre él se corre el **reconciliador**
(`tools/reconciler.py`) que produce `RECONCILIACION.md`, y el **backlog de auditoría**
(`tools/audit_backlog.py`) que ordena CRIT-1..3 / H-SEC primero (tier HIGH).

## 5.1/5.2/5.3 — Reconciliación y backlog crítico-primero

1. `reconcile(plan_text, repo_path)` cruza las afirmaciones "✅/COMPLETO" del
   `PLAN_MAESTRO_UNICO` contra el código real. La fuga multi-tenant (CRIT-1..3) se detecta
   por AST: si el plan dice "hardening completo" pero hay Views sin filtro → **CONTRADICHO**.
2. `contradictions_as_backlog()` convierte cada contradicción en un item **tier HIGH**.
3. `build_audit_backlog()` (`tools/audit_backlog.py`) ordena la auditoría 2026-06-01:
   **CRIT → H-SEC → H-* → NEW-INFRA → M-* → FE-***. Lo crítico se cierra antes de features nuevas.

## 5.5 — El gate de la fábrica es superconjunto del DoD de OmniERP

Cada paso del `docs/DEFINITION_OF_DONE.md` de OmniERP está cubierto por un gate mecánico:

| Paso del DoD de OmniERP | Gate de la fábrica que lo enforce |
|---|---|
| 1. Build verde (`check`, `makemigrations --check`, `tsc`, lint) | A9 `code_sandbox`: `makemigrations-check` (DURO), `tsc` (DURO), `eslint`, `lint-py` |
| 2. Tests verdes | A9: `pytest`/`manage.py test`, `coverage`, `vitest` (gates requeridos por stack — F1.1) |
| 3. Revisión de seguridad (`/security-review`) | A8 SecOps + **artefacto `SECURITY_REPORT.md`** (F1.4) + **A8.5 adversarial repo** (F2) |
| 4. Revisión de bugs/correctness | A7 QA + A6 Refactor (lee `gate_failures`) |
| 5. Revisión de gaps | A1 PR Final (cumplimiento real vs criterios) + A0 Revisor periódico |
| 6. Cero deuda nueva sin CTF | gate `all_green` (F1.5) + CTF fechados (`docs/ctf/`) |
| 7. R-CODE/R-PROC verificadas (sin auto-mentir) | **tabla de garantías derivada de gates** (F1.5), no checkbox del agente |
| Multi-tenant (R-CODE-1) | **gate de aislamiento AST DURO** (F1.2) + A8.5 (F2) |
| Code review humano obligatorio / no auto-merge de agente | **risk_tier_gate** (F3): tier HIGH→humano; auto-merge solo LOW + `all_green` |

**Conclusión:** la fábrica no solo replica el DoD de OmniERP — lo hace **mecánico y no
auto-atestiguado**, y añade dos capas que el DoD humano no tenía (aislamiento AST automático
y revisión adversarial a nivel repo).
