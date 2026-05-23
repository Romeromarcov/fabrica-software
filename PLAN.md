# Plan de Mejoras — Fábrica de Software
> Generado: 2026-05-23 | Estado: en progreso

---

## Diagnóstico de gaps

| # | Gap | Impacto | Bloqueante |
|---|-----|---------|-----------|
| G1 | El código generado **nunca se escribe al repo** — el PR queda vacío | Crítico | Sí |
| G2 | Stack **hardcodeado a Django + React/TypeScript/MUI** — otros stacks fallan | Alto | No |
| G3 | Sin lectura real del código existente (sin OpenClaw) para "continuar proyecto" | Alto | No |
| G4 | Dependencias nuevas (pip/npm) y `.env.example` no se actualizan automáticamente | Medio | No |
| G5 | No se genera infraestructura (Dockerfile, CI/CD) en proyectos nuevos | Medio | No |

---

## Tareas en orden de ejecución

---

### TAREA 1 — Agente 10: Code Writer `[PRIORIDAD CRÍTICA]`
**Objetivo:** Escribir los archivos generados por el pipeline al filesystem real del repositorio.  
**Posición en el pipeline:** después de A9 Sandbox, antes de A1 PR Final.  
**No usa LLM** — es lógica Python pura de parsing + escritura.

**Subtareas:**
- [ ] 1.1 Crear `tools/code_writer.py` — parser de bloques de código y escritor de archivos
- [ ] 1.2 Crear `nodes/a10_code_writer.py` — nodo del pipeline
- [ ] 1.3 Actualizar `graph.py` — insertar A10 entre A9 y A1
- [ ] 1.4 Actualizar `state.py` — añadir campo `files_written: list[str]`
- [ ] 1.5 Actualizar `ui/server.py` — mostrar archivos escritos en el panel de resultados
- [ ] 1.6 Actualizar `config.py` — constante `WRITE_TO_REPO` (on/off como safety switch)

**Formato que parsea:**
```
# === apps/modulo/models.py ===       ← Python/Django style
// === src/components/Foo.tsx ===     ← TypeScript/JS style  
<!-- === templates/foo.html ===       ← HTML style
# File: apps/modulo/serializers.py    ← Variante alternativa
```

**Comportamiento:**
- Crea directorios padres si no existen
- Nunca sobreescribe `.env`, `.env.*`, `*.key`, `*.pem` (seguridad)
- Guarda registro `files_written` en el state para el commit de A1
- Si `WRITE_TO_REPO=false` → modo dry-run, solo loguea sin escribir

---

### TAREA 2 — Agente 11: DevOps `[PRIORIDAD MEDIA-ALTA]`
**Objetivo:** Actualizar dependencias, documentar nuevas vars de entorno, y generar infraestructura para proyectos nuevos.  
**Posición en el pipeline:** después de A10 Code Writer, antes de A1 PR Final.  
**Sí usa LLM** — necesita entender el contexto del proyecto.  
**Condicional:** solo se activa si `needs_devops=True` (detectado por A1 PM al planificar).

**Subtareas:**
- [ ] 2.1 Crear `nodes/a11_devops.py` — nodo del pipeline
- [ ] 2.2 Actualizar `graph.py` — insertar A11 condicional entre A10 y A1
- [ ] 2.3 Actualizar `state.py` — añadir campo `needs_devops: bool`
- [ ] 2.4 Actualizar `nodes/human_nodes.py` — A1 PM detecta si el feature necesita DevOps
- [ ] 2.5 Añadir `MODEL_A11` a `config.py` y `.env.example`

**Responsabilidades de A11:**
- Lee `requirements.txt` / `package.json` actuales
- Detecta imports nuevos en el código generado
- Añade las dependencias faltantes con versión pinneada
- Detecta `os.getenv()` / `process.env.X` nuevos → documenta en `.env.example`
- Si `is_new_project=True`:
  - Genera `Dockerfile` (multi-stage: backend + frontend)
  - Genera `docker-compose.yml` básico
  - Genera `.github/workflows/ci.yml`
- Añade nota de migraciones al PR body si hay nuevos modelos Django

---

### TAREA 3 — Modo stack-agnostic vía STACK.md `[PRIORIDAD MEDIA]`
**Objetivo:** Los agentes A4, A5 y A7 deben adaptarse al stack real del proyecto en lugar de asumir siempre Django + React.

**Subtareas:**
- [ ] 3.1 Definir formato `STACK.md` — documento que describe el stack del proyecto
- [ ] 3.2 Crear `tools/stack_reader.py` — lee y parsea `STACK.md` del repo
- [ ] 3.3 Modificar `nodes/a4_backend.py` — inyectar instrucciones de stack en el prompt
- [ ] 3.4 Modificar `nodes/a5_frontend.py` — ídem para frontend
- [ ] 3.5 Modificar `nodes/a7_qa.py` — inyectar framework de testing correcto
- [ ] 3.6 Modificar `nodes/a0_arquitecto.py` — generar `STACK.md` al planificar nuevo proyecto
- [ ] 3.7 Actualizar UI — input para stack en la pantalla de nuevo proyecto (si no hay `STACK.md`)

**Stacks soportados inicialmente:**
- Backend: Django/DRF, FastAPI, Express/Node, Laravel
- Frontend: React/TypeScript, Vue 3, Next.js, Vanilla JS
- Testing: pytest, jest, vitest, phpunit

---

### TAREA 4 — Lector de código real para "continuar proyecto" `[PRIORIDAD MEDIA]`
**Objetivo:** Cuando OpenClaw no está disponible y el modo es `is_new=False`, darle a A0 un snapshot real del código del repositorio.

**Subtareas:**
- [ ] 4.1 Crear `tools/repo_scanner.py` — escanea el repo e indexa archivos clave
- [ ] 4.2 Modificar `nodes/a0_arquitecto.py` — en modo `is_new=False`, inyectar snapshot del repo
- [ ] 4.3 Definir qué archivos indexar por stack (models.py, urls.py, package.json, etc.)
- [ ] 4.4 Limitar el contexto para no exceder el token budget (top 30 archivos por tamaño + relevancia)

**Archivos que indexa `repo_scanner.py`:**
- Siempre: `README.md`, `ARCHITECTURE.md`, `DECISION_LOG.md`, `package.json`, `requirements.txt`
- Django: `models.py` de cada app, `urls.py` raíz, `settings.py`
- React: `src/types/*.ts`, rutas, servicios
- Cualquier stack: archivos modificados recientemente (git log --since=30 days)

---

## Orden de ejecución y dependencias

```
TAREA 1 (Code Writer)
    └── TAREA 2 (DevOps)      ← depende de que A10 exista para saber qué archivos actualizar
            └── TAREA 3 (Stack-agnostic)   ← mejora el código que A10 escribe
                    └── TAREA 4 (Repo Scanner)  ← mejora el contexto de A0
```

## Estado de avance

| Tarea | Estado | Archivos afectados |
|-------|--------|-------------------|
| T1 — Code Writer | ✅ Completado | tools/code_writer.py, nodes/a10_code_writer.py, graph.py, state.py, config.py |
| T2 — DevOps | ✅ Completado | nodes/a11_devops.py, graph.py, state.py, config.py, .env.example |
| T3 — Stack-agnostic | ✅ Completado | tools/stack_reader.py, nodes/a4/a5/a7/a0.py |
| T4 — Repo Scanner | ✅ Completado | tools/repo_scanner.py, nodes/a0_arquitecto.py |
