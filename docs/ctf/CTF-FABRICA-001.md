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

## Estado: WIRING COMPLETO — pendiente solo el sign-off E2E con langgraph

Resuelto (commit de cierre del wiring):
1. ✅ **Nombre de rama reconciliado.** `tools/branch_naming.feature_branch_name` es la
   ÚNICA fuente de verdad; la usan `git_tools.create_feature_branch` (con `feature_id`),
   `merge_coordinator._derive_branch_name` y el aislamiento por worktree. Ya no divergen.
2. ✅ **`run_parallel_batch._run_one` cableado:** crea un worktree por feature, corre el
   pipeline con `repo_path = worktree`, pre-setea `feature_branch` en el state (a1_pr_final
   commitea ahí, no crea otra rama). Fallback a repo compartido si el worktree falla.
   `merge_coordinator` fusiona esas ramas y limpia los worktrees (`_cleanup_worktrees`).
   Bandera: `PARALLEL_WORKTREE_ISOLATION` (default true).
3. ✅ **Validación E2E a nivel git** (`test_worktree_wiring.py::test_parallel_worktrees_merge_clean`):
   dos worktrees aislados escriben archivos distintos sin pisarse y ambas ramas mergean
   limpio a main. `.fabrica_worktrees/` se añade a `.gitignore` automáticamente.

## Lo único que queda (no bloquea el wiring, sí el flag en prod)

- **Sign-off E2E del pipeline completo** con `langgraph` + claves de IA (no disponible en el
  entorno del hardening). Es una corrida real de 2 features en paralelo de punta a punta.
  **Hasta ese sign-off, mantener `PARALLEL_FEATURES_ENABLED=false` en producción.**

## Criterio de cierre

✅ Mecánica git verificada E2E. Cierre final del CTF: una corrida real con langgraph de 2
features paralelos que terminan mergeados y sin colisión de archivos.
