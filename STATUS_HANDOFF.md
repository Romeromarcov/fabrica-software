# STATUS HANDOFF — fabrica-software

_Generado 2026-06-19 · para continuar en un entorno con **Docker + claves LLM + acceso GitHub/Railway admin**._

## Resumen

- **Suite:** 589 tests verde en local (`pytest tests/`).
- **Rama actual:** `feature/20260619-promotion-policy` (D2.3 + D3.1, pendiente de PR/merge).
- **Todo lo offline-verificable está hecho.** Lo que falta para el 100% requiere infra/credenciales que NO existen en el contenedor de la fábrica.

## Qué se completó (regla de oro: archivo existe + import ok + pytest pasa)

- **PLAN_HARDENING / ROADMAP / PLAN / PLAN_MEJORAS / PLAN_PLATAFORMA_V2:** 0 ítems sin marcar.
- **Última tanda (esta rama):**
  - `tools/promotion_policy.py` — D2.3 maduración por riesgo (LOW 1d / MEDIUM 3d / HIGH 7d + uso real). `tests/test_promotion_policy.py` (10).
  - `tools/release_report.py` — D3.1 reporte del PR de release develop→main. `tests/test_release_report.py` (7).

## Pendiente — TODO requiere el entorno Docker/credenciales

Todos los ítems abiertos viven en `PLAN_BLINDAJE_TOTAL.md`. Clasificados por bloqueo:

### A) Requiere host Docker + Railway (deploy real)
- **D1.2** — cablear gates de runtime DENTRO del `ephemeral_env` (flujo sandbox FAIL→A6). Lógica lista; falta `docker compose up` real contra la app.
- **D2.1** — rama `develop` + deploy automático a Railway `dev`.
- **D2.2** — `codebase_auditor` contra la app VIVA en dev + captura de errores de runtime (Sentry/logging) → `audit_backlog`.
- **D2.3 (señal viva)** — política ya implementada; falta alimentarla con días reales en dev + `reconciler` contra endpoints vivos.
- **D3.1 (creación PR)** — reporte ya implementado; falta crear el PR real en GitHub + recolectar señales vivas.
- **D3.2** — deploy a prod solo desde `main` + tag/release + rollback por redeploy del tag anterior.
- **D3.3** — smoke post-deploy contra prod + alerta Telegram + rollback en un comando.

### B) Requiere acción humana con permisos de admin GitHub
- **C2** — branch protection: configurar el check del revisor independiente + CI como requisito de merge a `main`. Es ajuste de *settings*, no código.

### C) ESCALADO — requiere sign-off humano (no abrir sin autorización explícita)
- **E5.1 / CTF-FABRICA-001** — cablear worktrees al `ThreadPoolExecutor` (paralelismo a nivel feature). Concurrencia real en el núcleo; `PARALLEL_FEATURES_ENABLED` permanece en `false`.

## Cómo retomar en el nuevo entorno

1. **Mergear esta rama primero:** abrir PR de `feature/20260619-promotion-policy` → `main`, CI verde, merge.
2. **Arranque:** `pip install -r requirements.txt` · `python -c "import langgraph, graph; print('env ok')"`.
3. **Verificar Docker:** `docker compose version` y un `tools/ephemeral_env.py` smoke real (D1.2) — primer ítem que se desbloquea con daemon Docker.
4. **Credenciales necesarias:** `ANTHROPIC_API_KEY` (o el proveedor LLM en uso) para los smokes E2E en vivo; token Railway con permisos de deploy (el inyectado aquí es solo de consulta); admin GitHub para C2.
5. **Orden sugerido:** D1.2 → D2.1 → D2.2 → D2.3(señal) → D3.1(PR real) → D3.2 → D3.3. C2 en paralelo (humano). E5.1 solo con sign-off.

## Flags que NUNCA cambiar
`AUTO_MERGE_ENABLED`, `PARALLEL_FEATURES_ENABLED` (ambos `false`).

## Bitácora
Detalle por PR en `ORCHESTRATOR_LOG.md`.
