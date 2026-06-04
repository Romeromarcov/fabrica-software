# Desplegar la Fábrica en Railway

Guía paso a paso para montar la fábrica en Railway, que trabaje sola sobre OmniERP y que
los features lleguen a producción **respetando las garantías** (gates + tier + review humano).

## Arquitectura (el puente es GitHub, no un deploy directo)

```
Railway: FÁBRICA  ──push+PR──►  GitHub: omni-erp  ──merge──►  Railway: OMNI-ERP PROD
 (este repo)                     (CI + tier_gate)              (deploy desde main)
```
La fábrica **nunca** toca la producción directamente: abre PRs. La producción se actualiza
cuando un commit entra a `main` y Railway despliega OmniERP desde GitHub.

---

## Prerrequisitos

- Cuenta Railway; OmniERP ya corriendo en Railway conectado a su repo de GitHub.
- Un **fine-grained GitHub PAT** con acceso **solo a `omni-erp`**: `contents: write`,
  `pull_requests: write`. (Blast radius mínimo: si se filtra, lo peor es un PR.)
- Claves de IA (Anthropic / OpenAI / Google / Z.ai / Kimi).

## Paso 1 — Crear el servicio de la fábrica

1. Railway → New Project → Deploy from GitHub → repo `fabrica-software`.
2. Railway detecta `railway.json` + `Dockerfile`. Build automático.
3. Healthcheck `/health` y `numReplicas: 1` ya vienen en `railway.json`.
   **No subir a 2+ réplicas:** el estado es SQLite (un solo escritor).

## Paso 2 — Volumen persistente

- Railway → servicio → Volumes → New Volume, **mount path `/data`**.
- Ahí viven `fabrica_state.db` (checkpoints LangGraph) y `runs/`. Sin volumen se pierde el
  estado en cada redeploy.
- `/workspace` (repos clonados) puede ser efímero: el clone-on-startup lo regenera. Si
  quieres acelerar reinicios, monta otro volumen en `/workspace`.
- **No se necesita base de datos** (Postgres/Redis): solo el volumen.

## Paso 3 — Variables de entorno

Copia [`.env.railway.example`](../.env.railway.example) en Railway → Variables. Claves:
claves de IA, `GITHUB_TOKEN`/`GITHUB_ACTOR`, `TARGET_REPOS`, rutas (`/data`, `/workspace`),
gates (`STRICT_GATES`, `TENANT_ISOLATION_GATE`, `ADVERSARIAL_REVIEW_ENABLED`), y arranque
conservador (`AUTO_MERGE_ENABLED=false`, `PARALLEL_FEATURES_ENABLED=false`, `USE_OPENCLAW=false`).

## Paso 4 — Primer arranque

Al iniciar, `entrypoint.sh` ejecuta `scripts/clone_targets.py`, que clona `omni-erp` en
`/workspace` usando `TARGET_REPOS` + `GITHUB_TOKEN`. En cada reinicio hace `fetch + reset`
(estado limpio). Verifica en los logs: `[clone_targets] omni-erp: OK`.

## Paso 5 — Trabajar y llegar a producción

1. La fábrica corre el pipeline sobre `/workspace/omni-erp`, abre **PR draft** en GitHub.
2. GitHub Actions (`ci.yml`) corre; el **risk_tier_gate** decide:
   - 🟢 LOW + gate verde → auto-merge (si `AUTO_MERGE_ENABLED=true`).
   - 🟡 MEDIUM → ventana de veto (Telegram).
   - 🔴 HIGH (core/auth/migraciones/dinero) → **espera tu revisión**; tú mergeas.
3. Merge a `main` → Railway (OmniERP) **despliega producción**.

**Recomendado:** una rama/entorno **staging** intermedio (ver abajo) para validar en un
entorno real antes de prod.

---

## ¿El entorno de desarrollo en Railway lo monto yo, o se crea automático?

**Las dos opciones son viables. Recomendación según etapa:**

### Opción A — Manual, una sola vez (recomendada para empezar)
Configura el proyecto OmniERP en Railway **una vez** con:
- GitHub integration (deploy de `main` → producción).
- Un **environment `staging`** que despliega desde la rama `develop` (DB propia de staging).
- **PR Environments** activados (Railway crea un entorno efímero por cada PR
  automáticamente). Así cada PR de la fábrica obtiene su deploy de preview sin código extra.

Con esto, la fábrica **solo abre PRs** y Railway hace todo el resto (crear entorno, desplegar
preview, tear-down al cerrar el PR). Robusto y estándar. Es lo que sugiero para v1.

### Opción B — Auto-provisión por API al vincular un repo nuevo (futuro)
Es **posible** automatizar: cuando registras un repo nuevo en la fábrica, llamar a la
Railway API (GraphQL) para crear servicio + environment + conectar el repo. Ya tienes el
cliente base: [`tools/railway_client.py`](../tools/railway_client.py) habla con la API
(`serviceInstanceDeploy`, etc.). Faltarían las mutaciones `serviceCreate` /
`environmentCreate` / `serviceConnect`.

**Trade-off honesto:** acopla la fábrica a la superficie de la API de Railway (más frágil,
hay que versionar mutaciones) y es difícil de testear sin tocar Railway real. Por eso **no se
implementó en v1**: la Opción A (PR Environments nativos) da el 90% del beneficio sin ese
acoplamiento. Cuando manejes muchos repos y quieras "un repo nuevo = entorno listo en 1 clic",
se añade `ensure_railway_environment(repo)` sobre `railway_client` como mejora.

---

## OpenClaw (opcional, re-habilitable)

Por defecto la fábrica usa **modo directo** (APIs de proveedores) — no necesita openclaw.
Para re-habilitar agentes con herramientas reales:
1. Build con `--build-arg INSTALL_OPENCLAW=true`.
2. Correr el gateway openclaw (`docker compose --profile openclaw up`, o un servicio Railway).
3. `USE_OPENCLAW=true`, `OPENCLAW_URL`, `OPENCLAW_GATEWAY_TOKEN`.

El mapeo de perfiles (`openclaw/client.py`) ya está corregido a los agentes actuales.

## Límites de seguridad

- La fábrica **no** tiene credenciales de la DB de producción ni deploy directo a contenedores.
- `GITHUB_TOKEN` con scope mínimo (solo `omni-erp`).
- `AUTO_MERGE_ENABLED=false` hasta que los falsos-OK sean cero (RUNBOOK §7.4).
