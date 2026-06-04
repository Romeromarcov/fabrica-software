# CTF-FABRICA-001 — Aislamiento por worktree en features paralelos

**Tipo:** Compromiso Técnico Fechado (R-PROC-6, convención del proyecto OmniERP aplicada a la fábrica)
**Creado:** 2026-06-03
**Vence:** antes de habilitar `PARALLEL_FEATURES_ENABLED=true` en producción
**Dueño:** founder

## Contexto

La Fase 4 del `PLAN_HARDENING_FABRICA` endurece el paralelismo:
- **F4.1 (hecho):** ningún feature tier HIGH corre en paralelo (`select_parallel_safe`).
- **F4.2 (hecho):** `merge_coordinator` no auto-fusiona en silencio lotes MEDIUM/HIGH; los
  conflictos en archivos core (models/settings/migrations) escalan a humano.
- **F4.3 (parcial):** falta cablear el **aislamiento por worktree**.

## El compromiso

`run_parallel_batch` (graph_project.py) corre cada feature en un hilo sobre el **mismo
working tree** del repo destino. Dos `a10_code_writer` concurrentes pueden pisarse los
archivos. Hoy se mitiga con:
- un **warning** explícito cuando hay >1 feature en el lote,
- `MAX_PARALLEL_FEATURES` bajo (default 2) y `PARALLEL_FEATURES_ENABLED=false` por defecto.

El primitivo de solución ya existe y está testeado: **`tools/worktree.py`**
(`create_worktree` / `remove_worktree` / `prune_worktrees`).

## Qué falta para cerrar (deuda dimensionada)

1. **Reconciliar el nombre de rama** entre `a1_pr_final.create_feature_branch`
   (`feature/YYYYMMDD-slug`) y `merge_coordinator._derive_branch_name`
   (`feature/<id8>-slug`) — hoy divergen; el merge paralelo depende de que coincidan.
2. Cablear `run_parallel_batch._run_one` para crear un worktree por feature, correr el
   pipeline con `repo_path = worktree`, y que `merge_coordinator` fusione esas ramas.
3. Validar **E2E** con `langgraph` + claves (no disponible en el entorno de desarrollo del
   hardening), porque toca concurrencia real.

No se cableó en la Fase 4 para **no introducir concurrencia no verificada** (violaría el
gate "cero deuda nueva sin compromiso fechado"): este CTF es ese compromiso.

## Criterio de cierre

Dos features que escriben archivos distintos corren en paralelo en worktrees separados,
sin pisarse, y `merge_coordinator` fusiona ambas ramas correctamente — verificado E2E.
