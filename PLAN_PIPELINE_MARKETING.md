# PLAN MAESTRO — Pipeline de Marketing (dominio `marketing/` de la Plataforma V2)

> Documento de dominio. Define la **fábrica de marketing** como el **segundo pipeline de
> referencia** de la plataforma runtime multi-pipeline descrita en `PLAN_PLATAFORMA_V2.md`
> (Fase 4). No es un fork de `fabrica-software`: es un grafo LangGraph de dominio que **vive
> dentro de la plataforma y consume el núcleo compartido**.
>
> **Principio rector e invariante heredado de V2:** la capacidad de **elegir un modelo
> distinto por cada agente** se preserva. Cada agente de marketing declara `model` opcional en
> el registry, con resolución en cascada `agent.model → marketing.default_model →
> config.GLOBAL_DEFAULT_MODEL`. La elección por agente es configuración, nunca obligación.

---

## 0. Visión

Transformar un objetivo de mercadeo en lenguaje natural — *"lanza la campaña de la Feria del
Transportista"*, *"anuncia el nuevo módulo del ERP"*, *"plan de contenido de enero para Global
Oil"* — en un flujo **de principio a fin**: planificación estratégica (ATL/BTL + calendario) →
producción (copy + arte) → control de marca y compliance → publicación programada → medición y
aprendizaje. Todo con **autonomía graduada por riesgo**, **human-in-the-loop proporcional**, y
reutilizando el núcleo endurecido que ya construiste para software.

```
                ┌──────────────────────────────────────────────┐
                │   META-CAPA CONVERSACIONAL (heredada de V2)    │
                │  "crea un agente de SEO" · "anuncia el feature" │
                └──────────────────────────────────────────────┘
                                    │
                ┌──────────────────────────────────────────────┐
                │           RUNTIME MULTI-PIPELINE               │
                │   software/   ►►►   marketing/   ◄── ESTE PLAN  │
                │   (cada uno = grafo LangGraph independiente)    │
                └──────────────────────────────────────────────┘
                                    │
                ┌──────────────────────────────────────────────┐
                │      NÚCLEO COMPARTIDO (no se reescribe)        │
                │  Router de modelos · Cost tracker (+ad spend)   │
                │  Memoria vectorial · Hooks · Auth/UI/Telegram   │
                │  Observabilidad · risk_classifier · checkpoints │
                └──────────────────────────────────────────────┘
```

---

## 1. Encaje en la Plataforma V2 — qué se reutiliza, qué es propio

El pipeline de marketing **no escribe infraestructura nueva**. Aporta solo lo específico del
dominio y consume todo lo demás del núcleo (Principio V2 #5: reutilizar, no reescribir).

| Componente | Del núcleo compartido | Propio de `marketing/` |
|---|:--:|:--:|
| Router de modelos (`base.py`) | ✅ | |
| Cost tracker / pricing | ✅ (se **extiende** con ad spend) | |
| Memoria vectorial (R1) | ✅ (namespace `marketing`) | |
| Hook engine (R2) | ✅ | hooks concretos (recordatorios, ingesta) |
| Auth / UI / Telegram | ✅ | |
| Observabilidad / trace IDs (M7) | ✅ | |
| `risk_classifier` | ✅ (se **adapta** a piezas/canales) | tabla de riesgo de dominio |
| Checkpointing + `interrupt_before` | ✅ | nodo de espera de asset |
| Agent registry / `graph_builder` | ✅ | entradas M0–M9 |
| **State** | | ✅ `MarketingState` |
| **Agentes + prompts** | | ✅ M0–M9 |
| **Gates de calidad** | | ✅ brand · tone · compliance · specs |
| **Output handlers** | | ✅ publicación a redes + scheduling |

---

## 2. Las tres divergencias de marketing (y cómo el núcleo V2 ya las resuelve)

La fábrica de software resolvió el 80% de los problemas. Lo que sigue son los **tres puntos
donde marketing diverge** — y cada uno se cubre con un mecanismo que ya existe en el núcleo.

### D1 — Espera de contenido físico (no es aprobación, es espera de artefacto)
A veces una pieza necesita una foto de planta o un video que solo un humano puede producir.
Esto **no** es un gate de aprobación: es una suspensión a la espera de un **archivo externo**.
Se resuelve con el mismo patrón que `stop_protocol`/`veto_window`:

- Nodo `M_esperando_asset` con `interrupt_before` + checkpoint `SqliteSaver` → el grafo se
  suspende sin congelar otras piezas (cada pieza es un hilo de estado independiente).
- Hook `on_asset_pending` → dispara recordatorios **escalados** por Telegram al responsable
  (reusa el motor de escalación que ya tienes del bot Asana/Telegram).
- **Inbox de ingesta** (output handler inverso): cuando el responsable sube el asset, un
  watcher destraba el checkpoint y el grafo **reanuda desde el nodo exacto**.

> Es tu `stop_protocol`, pero el input que destraba es un archivo en vez de una frase.

### D2 — Feedback de segundo orden, asíncrono (no bloquea la publicación)
El engagement y la conversión llegan **días después** de publicar. No puede ser un gate
síncrono. Es un nodo **desacoplado** que corre por cron y alimenta la memoria del Estratega —
exactamente el molde de tu `quality_tracker` → A1, renombrado:

- `PerformanceTracker` (sobre `learning_memory.py` / memoria vectorial, namespace `marketing`)
  ingiere métricas post-publicación (alcance, engagement, CTR, conversión, CPM si hubo pauta).
- Alimenta a **M1 Estratega** vía few-shot semántico: *"posts similares con este formato y
  horario rindieron X"*. Cierra el ciclo de aprendizaje sin bloquear el pipeline de producción.

### D3 — La publicación es irreversible (rompe el rollback)
Tu `pipeline_detenido` restaura `files_backup` o borra archivos nuevos. Un post publicado **no
se restaura**: ya lo vio la audiencia. Implicación de política, concreta:

- El **último gate (M8 Publisher)** es más conservador que `is_auto_mergeable`. Donde en
  software `LOW + gate verde + flag` permite auto-merge, en marketing el gate de publicación
  **nunca llega al 100% de autonomía**, ni en LOW, hasta acumular historial de confianza.
- "Despublicar" existe como output handler (archivar/ocultar), pero se trata como **mitigación
  de daño**, no como rollback. El diseño asume que publicar es definitivo.

---

## 3. `MarketingState` (estado del pipeline)

Análogo a `FabricaState`, con los campos del dominio. Listas acumulables con `operator.add`
igual que en software (`errors`, `cost_entries`).

```python
class MarketingState(TypedDict):
    # ── Identidad de la pieza ────────────────────────────────────────────────
    pieza_id: str
    pieza_nombre: str
    mode: Literal["campaña", "post", "lightning"]
    #  "campaña"   → flujo completo (plan + N piezas + ATL/BTL + seguimiento)
    #  "post"      → pieza única estándar (M1→M2/M3→M4→M5→M6→M7→M8)
    #  "lightning" → repost/story/UGC aprobado (M1→M4→M8; omite QA pesado)

    # ── Marca y canal ────────────────────────────────────────────────────────
    marca: str                       # "global_oil" | "lubrikca" | "club_global" | ...
    canales: list[str]               # ["instagram", "tiktok", ...]
    brand_brain_ref: str             # tono, arquetipo "El Experto", paleta, do's/don'ts

    # ── Plan (M1 Estratega) ──────────────────────────────────────────────────
    plan_campaña: Optional[str]      # plan ATL/BTL + calendario editorial
    plan_path: Optional[str]
    founder_approval: bool

    # ── Producción ───────────────────────────────────────────────────────────
    copy_output: Optional[str]       # M2 Copywriter
    arte_brief: Optional[str]        # brief del Director de Arte
    arte_assets: list[str]           # rutas a imágenes/videos generados (M3)
    pieza_ensamblada: Optional[str]  # M4 Editor: copy + arte adaptados por canal

    # ── Espera de contenido físico (D1) ──────────────────────────────────────
    needs_human_asset: bool          # M1 detecta que requiere material del mundo real
    asset_brief: Optional[str]       # specs + deadline para el responsable
    asset_recibido: bool             # destrabado por el inbox de ingesta

    # ── Gates de dominio ─────────────────────────────────────────────────────
    brand_passed: bool               # M5 QA de Marca (guidelines + specs del canal)
    brand_report: Optional[str]
    brand_iterations: int
    compliance_clear: bool           # M6 Compliance/Brand Safety (legal/reputacional)
    compliance_block: Optional[str]
    adversarial_clear: bool          # M6.5 Abogado del diablo (malinterpretación)
    preview_passed: bool             # M7 render en mockup del canal + specs (dim/longitud)

    # ── Publicación (M8) ─────────────────────────────────────────────────────
    scheduled_for: Optional[str]     # ISO datetime de publicación programada
    published: bool                  # irreversible (D3)
    publish_handler: str             # "instagram_graph" | "scheduler" | ...

    # ── Riesgo / autonomía graduada (heredado del núcleo) ────────────────────
    confidence_score: int            # 0-100 emitido por M1
    risk_level: str                  # LOW | MEDIUM | HIGH
    veto_deadline: Optional[str]

    # ── Costo (extendido) ────────────────────────────────────────────────────
    ad_spend_usd: float              # inversión de pauta si la pieza la lleva (D3/HIGH)

    # ── Aprendizaje (D2 — poblado asíncrono por PerformanceTracker) ──────────
    performance_ref: Optional[str]   # handle a métricas post-publicación

    # ── Control interno ──────────────────────────────────────────────────────
    current_agent: str
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list[CostEntry], operator.add]
```

---

## 4. Agentes del pipeline (entradas del registry)

Cada agente es una entrada en `agents/registry.json` (`pipeline: "marketing"`). El campo
`model` aprovecha la **ventaja de modelo-por-agente**: escritura, imagen, juez y razonamiento
estratégico tienen necesidades distintas. Los modelos abajo son **sugerencias por defecto**,
todas overrideables.

| ID | Rol | Análogo en software | Modelo sugerido (opcional) | Notas |
|----|-----|---------------------|----------------------------|-------|
| **M0** | Brief & Research | A0 prechat + AIDefence | conversacional | Refina el objetivo; valida input (PII, injection); inyecta social listening |
| **M1** | Estratega | A1 Planificador | razonamiento fuerte (Opus-class) | Plan ATL/BTL + calendario; clasifica riesgo + confidence; detecta `needs_human_asset` |
| **M2** | Copywriter | A4 Backend | fuerte en español/copy | Copys por canal según arquetipo |
| **M3** | Director de Arte | A5 Frontend | modelo de **imagen/video** + LLM director | Genera/dirige assets; corre **en paralelo a M2** (patrón R3) |
| **M4** | Editor / Ensamblador | A6 Refactor | medio | Une copy + arte, adapta formato por canal, unifica voz |
| **M5** | QA de Marca | A7 QA | juez barato (judge, M3 de V2) | brand_check + specs del canal (dimensiones, longitud, hashtags) |
| **M6** | Compliance & Brand Safety | A8 SecOps | modelo cuidadoso | Riesgo legal/reputacional; contexto venezolano (precio, político, fiscal) |
| **M6.5** | Adversarial | A8.5 Adversarial | modelo **distinto** (diversidad) | "¿Cómo se malinterpreta u ofende esta pieza?" |
| **M7** | Preview / Sandbox | A9 Sandbox | determinista (poco LLM) | Render en mockup real del canal; valida specs en "disco" |
| **M8** | Publisher | A10 + A1 PR Final | determinista | Programa/publica; **gate más estricto** (D3); registra ad spend |
| **M9** | Analista | — (nuevo, asíncrono) | análisis de datos | Fuera del grafo síncrono; pobla `PerformanceTracker` (D2) |
| **M10** | Documentador *(opcional)* | A12 | barato | Resumen de campaña, reporte ejecutivo para el GG |

**Paralelismo:** cuando una pieza requiere copy **y** arte, M2 y M3 corren en worktrees
lógicos aislados y M4 unifica — exactamente el patrón `A4+A5 → A6` de la Fase 2 de V2 (R3).

---

## 5. `pipelines/marketing/pipeline.yaml`

Expande el ejemplo que ya aparece en `PLAN_PLATAFORMA_V2.md` §2.2.

```yaml
name: marketing
default_model: gemini-3.5-flash          # default del pipeline; modelo por agente sigue opcional
state_schema: MarketingState
agents: [M0, M1, M2, M3, M4, M5, M6, M6.5, M7, M8]   # M9 corre por cron, fuera del grafo

human_checkpoints:
  - { after: M1, type: approval, policy: risk_based }   # plan (auto/veto/human según riesgo)
  - { after: M1, type: asset_wait, when: needs_human_asset }  # D1: espera de contenido físico
  - { before: M8, type: publish_gate, policy: never_full_auto }  # D3: último gate, nunca 100%

gates:                                    # gates de calidad propios del dominio
  - brand_check        # M5
  - specs_check        # M5 (dimensiones/longitud/formato por canal)
  - compliance_check   # M6
  - adversarial_check  # M6.5 (solo risk_level=HIGH, como el debate de software)

modes:
  campaña:   { agents: all,                          max_brand_iter: 3 }
  post:      { agents: [M1,M2,M3,M4,M5,M6,M7,M8],    max_brand_iter: 2 }
  lightning: { agents: [M1,M4,M8],                   skip_gates: true   }  # < 90s

output:
  handlers:
    - { id: instagram_graph, type: social, channel: instagram }
    - { id: scheduler,       type: schedule }     # programación diferida
    - { id: notion,          type: doc, when: documentador }  # reporte/calendario
  destination_default: scheduler

triggers:                                 # orquestación entre pipelines (V2 Fase 8)
  - on: "software.feature_merged"         # ⭐ el caso estrella (ver §8)
    map: { pieza_nombre: input.title, brief: input.changelog, marca: "omni_erp" }
    mode: post
```

---

## 6. Modos de ejecución (graduación de rigor)

Calca `completo / lite / lightning` de software:

- **`campaña`** — objetivo amplio. M1 produce plan ATL/BTL + calendario y **fan-out** a N
  piezas hijas (cada una su propio `MarketingState`), con seguimiento de cumplimiento vía
  Telegram/Asana. Equivale a `project_mode` de software.
- **`post`** — pieza única, flujo estándar con todos los gates.
- **`lightning`** — repost, story efímera, UGC ya aprobado. `M1 → M4 → M8`, salta QA pesado.
  Para reacción rápida. Target < 90 s, igual que el lightning de software (pero el gate de
  publicación D3 **no** se omite).

---

## 7. Autonomía graduada — `risk_classifier` adaptado al dominio

Se reutiliza `approval_action(tier, confidence, mode, project_mode)` **sin cambiar la lógica**.
Solo cambian las señales de entrada: la clasificación pasa de "qué archivos toca" a "qué tipo
de pieza y canal". Igual que en software, el clasificador es **determinista y la IA solo puede
subir el tier, nunca bajarlo**.

| Tier | Tipo de pieza | Acción (vía `approval_action`) |
|:----:|---------------|--------------------------------|
| 🟢 **LOW** | Post orgánico de producto, repost de UGC aprobado, story de catálogo | `veto` (ventana corta) — **nunca `auto` puro** por D3 |
| 🟡 **MEDIUM** | Copy con claim/beneficio, pieza de campaña, contenido que toca a la competencia | `veto` (ventana + revisión) |
| 🔴 **HIGH** | Menciona **precio**, tema económico/político/social, **lleva pauta pagada** (dinero), involucra figuras públicas, respuesta a crisis | `human` obligatorio + **panel adversarial** (M6.5) |

> Matiz D3 frente a software: el piso de marketing es más alto. Donde software auto-aprueba en
> LOW, marketing usa como mínimo `veto` (publica tras N min salvo veto del founder). La pauta
> pagada es **siempre HIGH** porque compromete dinero real, análogo a cómo `migrations/` y
> `dinero/Decimal` son HIGH en tu `risk_classifier` actual.

---

## 8. Orquestación entre pipelines — el caso estrella `software → marketing`

La razón por la que construir marketing **dentro** de la plataforma (y no aparte) vale la pena:
el bus de eventos de la Fase 8 de V2 conecta los dominios.

```
   pipeline software:  feature "Modo Kiosco POS" → A1 PR Final → merge
                                         │  emite evento  software.feature_merged
                                         ▼
   pipeline marketing: trigger → M1 (mode=post, brief=changelog)
                       → genera anuncio del feature en RRSS
                       → gate de publicación (founder aprueba) → programado
```

Cuando mergeas un feature del ERP, la fábrica de marketing **propone automáticamente** el
contenido para anunciarlo. Otros triggers naturales: `marketing.campaña_cerrada → M9` reporte
ejecutivo; `crm.cliente_nuevo → marketing` secuencia de bienvenida; un cron de calendario →
piezas recurrentes.

---

## 9. Roadmap por fases

> **Dependencia dura:** este pipeline requiere la **Fase 0 de V2** completa (agent registry +
> `graph_builder.py` + schemas Pydantic + hook engine). Sin el grafo data-driven, marketing
> tendría que hardcodearse y duplicar el núcleo. Fase 0 de V2 es el prerequisito #1.

Esfuerzo: 🟢 bajo · 🟡 medio · 🔴 alto.

### FASE M0 — Prerequisito (en V2)
- Confirmar Fase 0 de V2 (registry, `graph_builder`, Pydantic, hooks) operativa.
- Confirmar Fase 4 de V2 (runtime multi-pipeline: descubrimiento de `pipelines/*/`, state por
  pipeline, output handlers pluggables).

### FASE M1 — MVP de densidad (un canal, una marca, end-to-end con humano)
**Objetivo:** una pieza real publicada por el pipeline, con aprobación humana total.
- 🟡 `MarketingState` + agentes M1, M2, M3, M4, M5, M8 en el registry.
- 🟢 `pipeline.yaml` mínimo: `M1 → (M2 ∥ M3) → M4 → M5 → M8`, modo `post`.
- 🟢 Un solo canal: **Instagram** (Meta Graph API) y una sola marca: **Global Oil**.
- 🟢 Gate de publicación manual (founder aprueba siempre — aún sin autonomía).
- ✅ **Gate de fase:** un post diseñado, escrito, validado por marca y publicado por la fábrica.

> Aplica tu propio principio: **densidad antes que amplitud**. No "todas las redes con todos los
> agentes": un flujo completo, una marca, un canal. Y **operación manual antes que automatización**.

### FASE M2 — Calidad y autonomía graduada
- 🟡 M6 Compliance/Brand Safety + M6.5 Adversarial (solo HIGH, como el debate de software).
- 🟢 Tabla de riesgo de dominio en `risk_classifier`; conectar `approval_action` (auto/veto/human).
- 🟢 M7 Preview: render en mockup del canal + `specs_check` (dimensiones, longitud, hashtags).
- ✅ Posts LOW/MEDIUM pasan a `veto` (ventana); HIGH sigue manual.

### FASE M3 — Flujo de contenido físico (D1)
- 🟡 Nodo `M_esperando_asset` con `interrupt_before` + checkpoint.
- 🟢 Hook `on_asset_pending` → recordatorios escalados por Telegram (reusa el bot existente).
- 🟢 Inbox de ingesta (watcher) que destraba el checkpoint al recibir el asset.

### FASE M4 — Aprendizaje (D2)
- 🟡 `PerformanceTracker` sobre `learning_memory.py` (namespace `marketing`); ingesta de
  métricas post-publicación por cron (M9 Analista).
- 🟢 Few-shot semántico a M1: el plan siguiente se informa con lo que rindió.

### FASE M5 — Amplitud de canales
- 🟢 Output handlers adicionales: TikTok, LinkedIn, X, YouTube, Facebook.
- 🟡 Scheduling inteligente (mejor horario por canal/audiencia, informado por M9).
- 🟢 Repurposing: un asset grande → reel + carrusel + story (variantes por handler).

### FASE M6 — Orquestación software → marketing
- 🟡 Trigger `software.feature_merged → marketing` (bus de eventos, V2 Fase 8).
- 🟢 Triggers de calendario recurrentes; reporte ejecutivo `campaña_cerrada → M9 → notion`.

### FASE M7 — ATL/BTL, pauta y comunidad
- 🟡 `cost_tracker` extendido con **ad spend**; M8 registra inversión; ROI/ROAS en M9.
- 🟡 Seguimiento de cumplimiento ATL/BTL con notificaciones a responsables (Asana/Telegram).
- 🔴 Community management: agente de respuesta a comentarios/DMs + detección de crisis
  (alimenta triggers de respuesta sensible → HIGH).

### FUTURO (no priorizado)
- 🔴 Social listening avanzado (menciones, competencia, tendencias) como fuente continua de M0.
- 🟡 Agentes dinámicos de marketing vía **Agent Builder** de V2 (Fase 5): *"crea un agente de
  SEO"*, *"añade un agente de email marketing"* → registrados sin tocar código.

---

## 10. Principios transversales

1. **Reutilizar el núcleo, no reescribir.** Router de modelos, cost_tracker, memoria vectorial,
   hooks, risk_classifier, checkpoints, Telegram, observabilidad: todo del núcleo compartido.
2. **Modelo por agente opcional, nunca removido.** Resolución en cascada agente → pipeline →
   global (invariante de V2).
3. **Aprobación proporcional al riesgo** — y con un piso más alto que software por D3.
4. **El último gate (publicación) nunca llega al 100% de autonomía.** La irreversibilidad manda.
5. **Densidad antes que amplitud / operación manual antes que automatización.** El MVP es una
   marca, un canal, un flujo completo con humano. La autonomía se gana con historial.
6. **Compatibilidad:** marketing no toca ni rompe el pipeline `software`. Son dominios aislados
   sobre el mismo núcleo.
7. **Data-driven:** comportamiento en `registry.json` / `pipeline.yaml`, no hardcodeado.

---

## 11. Quick wins para arrancar

1. **Fase M1 completa** (un post real publicado end-to-end) — valida toda la arquitectura con
   el mínimo de superficie.
2. **Reutilizar `risk_classifier` + `approval_action`** tal cual con la tabla de dominio —
   autonomía graduada casi gratis.
3. **Trigger `software.feature_merged`** — demo de altísimo impacto: el ERP se anuncia solo.
4. **`PerformanceTracker` como rename de `quality_tracker`** — el ciclo de aprendizaje reusa
   código probado.

---

_Fin del plan. Alineado con `PLAN_PLATAFORMA_V2.md`. Priorización abierta a iteración del fundador._
