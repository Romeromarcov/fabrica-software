# Línea base — Comportamiento de la fábrica antes del hardening (Fase 0.2)

**Fecha:** 2026-06-03
**Rama:** `feature/hardening-garantias`
**Propósito:** registrar el comportamiento *actual* (pre-Fase 1) para poder medir el efecto
del endurecimiento. Esta es la foto del "antes".

---

## 1. Detección de stack de OmniERP (verificada, reproducible)

Comando:
```bash
python -c "from tools.code_sandbox import _detect_stack; \
print(_detect_stack(r'C:/Users/PC/Proyectos/omni-erp/backend')); \
print(_detect_stack(r'C:/Users/PC/Proyectos/omni-erp/frontend'))"
```

Resultado:
```
BACKEND  : {'python': True,  'django': True,  'node': False, 'typescript': False, 'has_pytest': True,  'has_jest': False}
FRONTEND : {'python': False, 'django': False, 'node': True,  'typescript': True,  'has_pytest': False, 'has_jest': True}
```

> **Nota de portabilidad:** `_detect_stack` usa `pathlib`, que en Windows **no** entiende
> rutas estilo git-bash (`/c/Users/...`). Usar rutas Windows (`C:/Users/...`). Las rutas que
> recibe la fábrica en runtime vienen de `config.resolve_repo_path`, que ya son correctas.

**Gates que OmniERP-backend debería ejecutar (Django+pytest):** pytest, coverage,
migrate-check, lint-py, (mypy si está). **Frontend (node+ts+jest):** tsc, npm-build, vitest, eslint.

---

## 2. El agujero soft-fail (lo que la Fase 1.1 cierra)

Estado actual de `tools/code_sandbox.py::run_all_checks` (líneas ~259-264):

```python
if not any_exec:
    lines += ["AVISO: No se ejecuto ningun check (herramientas no instaladas)."]
    all_passed = True          # ← AGUJERO: sin herramientas, el gate PASA
```

Además, cada `_check_*` devuelve `skipped=True` sin distinguir entre:
- **N/A legítimo** (p. ej. "no es proyecto Python" en un repo Node), y
- **tool_missing** (p. ej. "pytest no instalado" en un repo Python con tests).

**Consecuencia (baseline):** un entorno sin pytest/tsc instalados produce
`passed=True` aunque el stack del repo declare esas capacidades. "Verde" no prueba calidad.
La Fase 1.1 convierte `tool_missing` de un gate requerido-por-stack en **FAIL**.

## 3. Ausencia de gate de aislamiento multi-tenant (lo que cierra la Fase 1.2)

`run_all_checks` no contiene ningún check de aislamiento por `id_empresa`. Los `hard_gates`
actuales son solo `["tsc", "npm-build"]`. → El patrón CRIT-1..3 de OmniERP (DetailView de core
sin filtro tenant) **no es detectable** por el sandbox actual.

## 4. Alcance de A8 SecOps (baseline para la Fase 2)

`nodes/a8_secops.py` recibe `state['backend_code']` / `state['frontend_code']` — el **snippet
generado**, no el repo completo. → No puede ver una `DetailView` *vecina* que filtre datos.
Este es el punto ciego que la Fase 2 (A8.5 a nivel repo) cubrirá.

## 5. Modo `--audit` (no ejecutado en esta línea base)

`cli.py cmd_new_project(..., audit=True)` invoca A0 (LLM) → requiere `ANTHROPIC_API_KEY` /
`GOOGLE_API_KEY` y red. No se ejecuta en este entorno offline. El comportamiento de A0/audit
no cambia en Fase 1; su baseline se capturará en la Fase 5 (reconciliación plan↔código) cuando
haya claves disponibles.

---

## Cómo reproducir esta línea base

```bash
cd C:\Users\PC\Proyectos\fabrica-software
python -m pytest tests/ -q          # tras Fase 0.4: la suite de la fábrica
python -c "from tools.code_sandbox import _detect_stack; print(_detect_stack(r'C:/Users/PC/Proyectos/omni-erp/backend'))"
```
