# Plan de Mejoras — Fábrica de Software
> Versión: 2026-05-25 | Estado: BORRADOR
> Bloques I–VI completados. Este plan cubre el camino desde VII en adelante.

> **✅ VERIFICACIÓN 2026-06-16** — `tests/test_mejoras_verification.py` (28 tests) confirma
> con pruebas (no solo "código existe") los siguientes ítems, antes CLAIMED:
> - **P0-A Lightning Mode** — `"lightning"` válido en `state.py`; el routing salta DB/MCP/QA/
>   SecOps/Sandbox/DevOps hasta `lightning_complete`.
> - **P0-B / IX-1 Auth** — `auth_manager`: hash+verify de password (salteado), matriz `can()`
>   por rol (owner/developer/viewer).
> - **VII-1 Prechat** — `a0_prechat.extract_refined_brief` (ambas ramas).
> - **VII-2 / VIII-1 Event bus** — emit/get_recent_events + intervención post→pop (consumo atómico).
> - **VII-3 Railway** — `railway_client` (async, `_gql`/`_headers` con red mockeada).
> - **VIII-2 Routing dinámico** — `dynamic_router.predict_routing` (flags bool, sin crash sin historial).
> - **VIII-3 Debate** — flag `DEBATE_PANEL_ENABLED` (default false, opt-in) + `MODEL_DEBATE`
>   AHORA cableados en `config.py` y respetados por `graph._route_after_plan_or_debate`.
> - **IX-2 PWA** — `ui/static/manifest.json` + `sw.js` presentes; **sender VAPID** ahora
>   implementado (`tools/push_notify.py`, `pywebpush`, degradación elegante sin claves) y
>   cableado en `emit_pipeline_end`; endpoint `GET /api/push/vapid-public-key`.
> - **VIII-1 Intervención mid-flight** — VERIFICADO: `call_agent` consulta `pop_intervention`
>   antes de llamar al LLM e inyecta la instrucción del Founder como override (y la consume).
> Pendiente (no verificado por tests aquí): push VAPID end-to-end real (requiere navegador +
> claves VAPID configuradas) — el envío está cubierto con `pywebpush` mockeado.

---

## Criterios de priorización

| Criterio | Peso |
|---|---|
| Impacto en el ciclo de desarrollo (velocidad + autonomía) | 40% |
| Complejidad de implementación / riesgo de regresión | 30% |
| Frecuencia de uso (cuánto lo toca el Founder cada día) | 20% |
| Deuda técnica que genera si se deja para después | 10% |

---

## Mapa de Bloques

```
Bloques I-VI  ──► COMPLETADOS
Bloque P0     ──► Lightning mode + GitHub OAuth        (1–2 días)
Bloque VII    ──► Chat pre-planificación + Observabilidad + Railway   (1 semana)
Bloque VIII   ──► Intervención mid-flight + Routing dinámico + Debate (2 semanas)
Bloque IX     ──► Multi-usuario + PWA Remote Control   (3–4 semanas)
```

---

## P0 — Wins inmediatos (hacer esta semana)

### P0-A: Lightning Mode (ejecución ultra-rápida)

**¿Qué es?**
Un tercer modo de ejecución (junto a `completo` y `lite`) que omite SecOps, Quality, PR-Sender y Merger, y ejecuta solo A1→A2→A3→A10. Para hotfixes y prototipos desechables.

**Archivos a modificar**

| Archivo | Cambio |
|---|---|
| `config.py` | Añadir `LIGHTNING_MODE_AGENTS = ["a1", "a2", "a3", "a10"]` |
| `state.py` | Modo `"lightning"` válido en el Literal de `mode` |
| `graph.py` | Nueva ruta condicional que salta A6/A7/A8/A9/A11/A12 |
| `nodes/a1_planificador.py` | Añadir instrucción especial para lightning: "no planifiques tests ni SecOps" |
| `cli.py` | Flag `--mode lightning` |
| `ui/server.py` | Opción en el select de modo |
| `ui/templates/new_feature.html` | Mostrar badge "⚡ Lightning" cuando está activo |

**Routing**
```python
# graph.py — después de a1_planificador
def _route_mode(state):
    if state["mode"] == "lightning":
        return "a2_db"          # salta directamente; A3 y A10 siguen en cadena corta
    elif state["mode"] == "lite":
        ...
```

**DoD**
- `--mode lightning` pasa de `feature_name` a código commiteado en < 90 seg (repo pequeño)
- No llama A6, A7, A8, A9, A11, A12
- El MASTER_PLAN indica explícitamente "modo lightning — sin tests"
- Aparece badge ⚡ en la UI

---

### P0-B: GitHub OAuth (autenticación real)

**¿Qué es?**
Reemplazar el campo `github_token` en texto plano por un flujo OAuth 2.0 con GitHub. El token se almacena en la sesión Flask, no en el estado del agente.

**Archivos a modificar**

| Archivo | Cambio |
|---|---|
| `ui/server.py` | Rutas `/auth/github`, `/auth/callback`, `/auth/logout` |
| `ui/templates/base.html` | Botón "Conectar con GitHub" si no autenticado |
| `tools/git_tools.py` | Leer token desde `session["github_token"]` en vez de env |
| `config.py` | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` desde `.env` |
| `.env.example` | Añadir las dos variables |
| `requirements.txt` | `authlib>=1.3` |

**Flujo**
```
Founder → /auth/github → GitHub OAuth consent → /auth/callback
  → guarda token en Flask session (server-side, no en cookie)
  → redirige a / con badge "✅ GitHub conectado"
```

**DoD**
- Token nunca visible en HTML ni en logs
- Si el token expira, redirige a re-auth automáticamente
- Funciona con repos privados
- `git_tools.py` no lee `GITHUB_TOKEN` del env si hay token en sesión

---

## Bloque VII — Inteligencia de Interfaz (1 semana)

### VII-1: Chat pre-planificación con el A0

**¿Qué es?**
Una conversación interactiva en la UI antes de lanzar el feature. El Founder hace preguntas, el A0 responde y refina el brief. Al confirmar, el brief enriquecido se inyecta en A1.

**Archivos nuevos**

```
ui/templates/prechat.html          ← ventana de chat
ui/static/js/prechat.js            ← fetch streaming al endpoint
nodes/a0_prechat.py                ← nodo LLM de conversación
```

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `ui/server.py` | `POST /api/prechat` → stream SSE de respuesta del A0; `POST /api/prechat/confirm` → guarda brief refinado |
| `state.py` | `refined_brief: Optional[str]` en FabricaState |
| `nodes/a1_planificador.py` | Inyectar `refined_brief` en el prompt si existe |

**Protocolo SSE**
```
POST /api/prechat  {feature_name, message, history[]}
→ text/event-stream
  data: {"token": "..."}
  data: {"done": true, "refined_brief": "..."}
```

**Cuándo activar el chat**
- Solo si `PRECHAT_ENABLED=true` en `.env`
- El Founder puede saltar con "Lanzar directo"

**DoD**
- El chat soporta ≥5 turnos sin perder historial
- El brief refinado se guarda en `metadata.json` del feature
- A1 produce un plan más acotado cuando hay `refined_brief` (verificable con test de integración)

---

### VII-2: Observabilidad en vivo (UI Sessions)

**¿Qué es?**
Un panel en la UI que muestra en tiempo real el estado de cada agente: qué está haciendo ahora, cuánto costó, cuántas tokens usó, y el último log emitido.

**Archivos nuevos**

```
ui/templates/session_detail.html   ← vista por feature_id
ui/static/js/session_live.js       ← SSE consumer + render
tools/event_bus.py                 ← cola en memoria (asyncio.Queue)
```

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `ui/server.py` | `GET /api/sessions/<feature_id>/stream` → SSE; emite eventos desde `event_bus` |
| `nodes/base.py` | `call_agent()` emite `{"agent": label, "status": "start"\|"end", "tokens": n, "cost": $x}` al bus |
| `ui/templates/dashboard.html` | Link "Ver en vivo" por cada run activo |

**Estructura de evento**
```json
{
  "ts": "2026-05-25T14:32:01Z",
  "feature_id": "abc123",
  "agent": "A4 Backend",
  "status": "running",
  "last_log": "Generando endpoint /api/users...",
  "tokens_used": 1240,
  "cost_usd": 0.018
}
```

**DoD**
- El panel se auto-refresca sin polling (SSE puro)
- Muestra barra de progreso: cuántos agentes completados / total esperados
- Si el feature falla, el agente en rojo muestra el error resumido
- Funciona en paralelo: múltiples feature_ids en simultáneo

---

### VII-3: Railway básico (deploy con un click)

**¿Qué es?**
Desde la UI, el Founder puede hacer deploy del proyecto a Railway sin salir de Fábrica. Usa la Railway API v2.

**Archivos nuevos**

```
tools/railway_client.py            ← wrapper de Railway API
ui/templates/deploy.html           ← panel de deploy
```

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `config.py` | `RAILWAY_TOKEN`, `RAILWAY_PROJECT_ID` |
| `ui/server.py` | `POST /api/deploy/railway` → trigger deploy; `GET /api/deploy/status` → poll |
| `.env.example` | Variables Railway |

**Flujo**
```
Founder → click "Deploy a Railway"
  → railway_client.trigger_deploy(project_id, service_id)
  → SSE muestra logs de deploy en tiempo real (Railway API /deployments/logs)
  → Badge "✅ Deployed" o "❌ Failed" con link al deploy
```

**DoD**
- Deploy se dispara en < 3 seg desde el click
- Logs de Railway visibles en la UI sin salir
- Si el deploy falla, muestra el error de Railway y sugiere "Ver A10 logs"
- No almacena `RAILWAY_TOKEN` en git (solo en `.env`)

---

## Bloque VIII — Agencia Avanzada (2 semanas)

### VIII-1: Intervención mid-flight real

**¿Qué es?**
El Founder puede pausar un feature en curso y enviar una instrucción correctiva que el agente activo recibe en su próximo turno, sin abortar el run.

**Cómo funciona**
1. UI muestra botón "⏸ Intervenir" para cada run activo
2. Founder escribe la corrección en un textarea
3. La instrucción se guarda en `event_bus` con tipo `"intervention"`
4. El próximo `call_agent()` del nodo activo consulta el bus antes de llamar al LLM
5. Si hay intervención pendiente, la inyecta al inicio del prompt como `[FOUNDER_OVERRIDE]`

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `tools/event_bus.py` | Añadir `post_intervention(feature_id, text)` y `pop_intervention(feature_id)` |
| `nodes/base.py` | `call_agent()` llama `pop_intervention()` antes de construir el prompt |
| `ui/server.py` | `POST /api/sessions/<feature_id>/intervene` |
| `ui/templates/session_detail.html` | Panel de intervención |

**DoD**
- La intervención llega al siguiente agente en ≤ 1 ciclo de LLM
- Si el feature ya terminó cuando llega la intervención, el bus la descarta con warning
- La intervención queda registrada en `metadata.json`

---

### VIII-2: Routing dinámico basado en historial

**¿Qué es?**
En vez de routing estático (`SKIP_BACKEND: true/false`), el sistema consulta el historial de features del proyecto para decidir qué agentes son probablemente necesarios.

**Implementación**

```python
# tools/dynamic_router.py  (nuevo)
def predict_required_agents(
    feature_name: str,
    feature_description: str,
    project_id: str,
) -> dict[str, bool]:
    """
    Usa TF-IDF sobre el historial de features para predecir
    si este feature necesita backend, frontend, DB, etc.
    Retorna {"needs_backend": bool, "needs_frontend": bool, ...}
    """
```

- Carga los últimos N features del proyecto desde `decisions.jsonl`
- Vectoriza con sklearn TF-IDF (sin LLM, < 10ms)
- Compara con features similares y sus flags reales
- Si confianza < 70%, delega la decisión al A1 como siempre

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `tools/dynamic_router.py` | Nuevo |
| `nodes/a1_planificador.py` | Consulta `predict_required_agents()` e inyecta sugerencia al prompt |
| `requirements.txt` | `scikit-learn>=1.4` (ya posiblemente instalado) |

**DoD**
- En proyectos con ≥ 10 features en historial, las predicciones son correctas en ≥ 75% de los casos
- No añade latencia perceptible (< 50ms)
- La predicción se registra en `metadata.json` junto al resultado real (para medir accuracy)

---

### VIII-3: Debate inter-agente (solo features HIGH RISK)

**¿Qué es?**
Cuando `RISK_LEVEL=HIGH`, antes de que A2/A4/A5 ejecuten, se activa un "panel de revisores" de 2 agentes que evalúan el plan y proponen objeciones. A1 responde. Solo si hay acuerdo se continúa.

**¿Por qué solo HIGH RISK?**
El costo (3× LLM calls) solo se justifica cuando el riesgo de regresión es real: migraciones, cambios de API pública, refactors amplios.

**Flujo**

```
A1 produce MASTER_PLAN con RISK_LEVEL=HIGH
  → debate_panel(state)
     ├─ Revisor 1 (A_rev1): "Mi objeción es X"
     ├─ Revisor 2 (A_rev2): "Mi objeción es Y"
     └─ A1 responde: "Actualizo el plan: Z"
  → MASTER_PLAN v2 con objeciones resueltas
  → continúa a A2
```

**Archivos nuevos**

```
nodes/debate_panel.py              ← orquesta los 2 revisores + A1 reply
```

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `graph.py` | Edge condicional: si `risk_level == "HIGH"` → `debate_panel` antes de A2 |
| `config.py` | `DEBATE_PANEL_ENABLED=true`, `MODEL_DEBATE=claude-3-5-haiku-20241022` (más barato) |
| `state.py` | `debate_log: list[dict]` |

**Prompt estructura**
```
Revisor 1: Eres un arquitecto senior. El plan es:
{master_plan}
Identifica los 2 riesgos más críticos. Sé breve y directo.
```

**DoD**
- Solo activa para features con RISK_LEVEL=HIGH
- El debate tiene máximo 1 ronda (no loops infinitos)
- El MASTER_PLAN v2 incluye sección "DEBATE_RESOLUTIONS"
- Si ambos revisores dicen "sin objeciones", salta directo a A2
- Coste del debate < $0.05 (usar Haiku, prompts cortos)

---

## Bloque IX — Escala y Control (3–4 semanas)

### IX-1: Multi-usuario y RBAC

**¿Qué es?**
Soporte para múltiples Founders con roles diferenciados: `owner`, `developer`, `viewer`.

**Stack sugerido**
- `Flask-Login` para sesiones
- SQLite `users` table (o Postgres si Railway)
- Roles en JWT claims si se usa OAuth

**Archivos nuevos**

```
tools/auth.py                      ← login_required decorator + role check
ui/templates/login.html
ui/templates/admin_users.html      ← gestión de usuarios (owner only)
models/user.py                     ← User model
```

**Matriz de permisos**

| Acción | owner | developer | viewer |
|---|---|---|---|
| Crear proyecto | ✅ | ❌ | ❌ |
| Lanzar feature | ✅ | ✅ | ❌ |
| Intervenir mid-flight | ✅ | ✅ | ❌ |
| Ver sesiones | ✅ | ✅ | ✅ |
| Deploy | ✅ | ❌ | ❌ |

**DoD**
- Login con email + password (bcrypt)
- GitHub OAuth también funciona para login (reutiliza P0-B)
- El `owner` puede invitar usuarios por email
- Todas las rutas protegidas por `@login_required`

---

### IX-2: PWA Remote Control

**¿Qué es?**
La UI actual funciona como Progressive Web App instalable en móvil. El Founder puede aprobar planes, lanzar features y ver observabilidad desde el teléfono.

**Implementación**

```
ui/static/manifest.json            ← PWA manifest
ui/static/sw.js                    ← Service Worker (cache offline)
ui/static/icons/                   ← íconos 192x192, 512x512
```

**Funcionalidades móviles**
- Push notifications cuando un feature completa o falla (Web Push API)
- Pantalla de aprobación de ROADMAP optimizada para touch
- Panel de intervención mid-flight desde móvil

**Archivos modificados**

| Archivo | Cambio |
|---|---|
| `ui/templates/base.html` | `<link rel="manifest">` + meta theme-color |
| `ui/server.py` | `GET /sw.js`, `POST /api/push/subscribe` |
| `config.py` | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` |

**DoD**
- "Instalar app" disponible en Chrome Android / Safari iOS
- Notificación push llega en ≤ 5 seg del evento
- Funciona con pantalla apagada
- Score Lighthouse PWA ≥ 90

---

## Tabla resumen de esfuerzo

| Ítem | Esfuerzo estimado | Dependencias | ROI |
|---|---|---|---|
| P0-A Lightning Mode | 4 h | — | 🔥🔥🔥 |
| P0-B GitHub OAuth | 6 h | — | 🔥🔥🔥 |
| VII-1 Chat pre-planificación | 1 día | — | 🔥🔥🔥 |
| VII-2 Observabilidad en vivo | 1 día | `event_bus.py` | 🔥🔥🔥 |
| VII-3 Railway deploy | 1 día | VII-2 (usa SSE) | 🔥🔥 |
| VIII-1 Intervención mid-flight | 1.5 días | VII-2 | 🔥🔥🔥 |
| VIII-2 Routing dinámico | 1 día | historial ≥10 features | 🔥🔥 |
| VIII-3 Debate inter-agente | 1 día | — | 🔥 |
| IX-1 Multi-usuario RBAC | 3–4 días | P0-B | 🔥🔥 |
| IX-2 PWA Remote Control | 2–3 días | VII-2 + IX-1 | 🔥🔥 |

---

## Orden de implementación recomendado

```
Semana 1
  └── P0-A (Lightning Mode)          ← sin dependencias, alto ROI
  └── P0-B (GitHub OAuth)            ← sin dependencias, base para IX-1
  └── VII-1 (Chat pre-planificación) ← independiente, cambia UX

Semana 2
  └── tools/event_bus.py             ← infraestructura compartida
  └── VII-2 (Observabilidad)         ← depende de event_bus
  └── VII-3 (Railway deploy)         ← depende de SSE de VII-2

Semana 3
  └── VIII-1 (Intervención mid-flight) ← depende de event_bus
  └── VIII-2 (Routing dinámico)      ← independiente
  └── VIII-3 (Debate inter-agente)   ← independiente

Semana 4+
  └── IX-1 (Multi-usuario RBAC)      ← depende de P0-B
  └── IX-2 (PWA)                     ← depende de VII-2 + IX-1
```

---

## Qué NO está en este plan (y por qué)

| Idea descartada | Razón |
|---|---|
| Modelo propio fine-tuneado | Costo y tiempo de datos de entrenamiento no justificados aún |
| Marketplace de agentes | Requiere multi-tenant maduro (IX-1 primero) |
| Integración con Jira/Linear | La UI propia cubre el 90% del caso de uso con menos fricción |
| Auto-escalado de infra | Railway lo maneja; no vale la pena abstraer encima |

---

*Generado por el asistente en sesión 2026-05-25. Actualizar al completar cada bloque.*
