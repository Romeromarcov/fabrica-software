"""
tools/vector_memory.py — Memoria vectorial (PLAN_PLATAFORMA_V2 R1, Fase 2).

Complementa `learning_memory`/`fewshot_builder` con búsqueda semántica de planes y
soluciones pasadas, con NAMESPACES por pipeline y por repo.

Diseño en dos capas (sin imponer dependencias pesadas a la fábrica):
  - Backend ChromaDB si está instalado Y `VECTOR_MEMORY_ENABLED=true` → búsqueda semántica real.
  - FALLBACK siempre disponible: almacén JSONL + ranking por solapamiento de keywords.
    Garantiza que la API funciona en CI/offline sin `chromadb` instalado.

Sin side effects al importar; `chromadb` se importa de forma perezosa.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _store_dir() -> Path:
    try:
        from config import FABRICA_DIR
        return Path(FABRICA_DIR) / "data" / "vector_memory"
    except ImportError:
        return Path("data/vector_memory")


def _safe_ns(namespace: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", namespace or "default")


def _jsonl_path(namespace: str) -> Path:
    return _store_dir() / f"{_safe_ns(namespace)}.jsonl"


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")}


# ── Disponibilidad del backend semántico ─────────────────────────────────────

def chromadb_available() -> bool:
    """True si `chromadb` está instalado (no implica que esté habilitado)."""
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


def backend() -> str:
    """Backend efectivo: 'chromadb' si está habilitado e instalado, si no 'keyword'."""
    try:
        from config import VECTOR_MEMORY_ENABLED
    except ImportError:
        VECTOR_MEMORY_ENABLED = False
    if VECTOR_MEMORY_ENABLED and chromadb_available():
        return "chromadb"
    return "keyword"


# ── API pública ───────────────────────────────────────────────────────────────

def add_memory(namespace: str, text: str, metadata: dict | None = None) -> bool:
    """
    Guarda una entrada en la memoria del namespace. Siempre persiste en el almacén
    JSONL (fuente de verdad portable); el backend chromadb lo indexa además si está activo.
    """
    if not text:
        return False
    entry = {"text": text, "metadata": metadata or {}}

    path = _jsonl_path(namespace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        from tools.degradation import best_effort_log
        best_effort_log("Persistencia de memoria vectorial", exc, logger)
        return False

    if backend() == "chromadb":
        try:
            _chroma_add(namespace, text, entry["metadata"])
        except Exception as exc:  # noqa: BLE001 — el fallback JSONL ya guardó
            logger.warning("vector_memory: indexado chromadb falló (%s); queda el JSONL", exc)
    return True


def query(namespace: str, text: str, top_k: int = 3) -> list[dict]:
    """
    Devuelve las top_k entradas más relevantes a `text`. Usa chromadb si está activo;
    si no, ranking por solapamiento de keywords sobre el JSONL.
    """
    if backend() == "chromadb":
        try:
            return _chroma_query(namespace, text, top_k)
        except Exception as exc:  # noqa: BLE001 — degradar a keyword
            logger.warning("vector_memory: query chromadb falló (%s); fallback keyword", exc)
    return _keyword_query(namespace, text, top_k)


def _keyword_query(namespace: str, text: str, top_k: int) -> list[dict]:
    path = _jsonl_path(namespace)
    if not path.exists():
        return []
    q = _tokens(text)
    if not q:
        return []
    scored: list[tuple[float, dict]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            overlap = q & _tokens(entry.get("text", ""))
            if overlap:
                scored.append((len(overlap) / len(q), entry))
    except (OSError, ValueError) as exc:
        from tools.degradation import best_effort_log
        best_effort_log("Lectura de memoria vectorial", exc, logger)
        return []
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{"text": e["text"], "metadata": e.get("metadata", {}), "score": round(s, 4)}
            for s, e in scored[:top_k]]


# ── Backend ChromaDB (perezoso) ───────────────────────────────────────────────

def _chroma_client():
    import chromadb
    persist = _store_dir() / "chroma"
    persist.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist))


def _chroma_add(namespace: str, text: str, metadata: dict) -> None:
    client = _chroma_client()
    col = client.get_or_create_collection(_safe_ns(namespace))
    import hashlib
    doc_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    col.add(documents=[text], metadatas=[metadata or {}], ids=[doc_id])


def _chroma_query(namespace: str, text: str, top_k: int) -> list[dict]:
    client = _chroma_client()
    col = client.get_or_create_collection(_safe_ns(namespace))
    res = col.query(query_texts=[text], n_results=top_k)
    out: list[dict] = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, doc in enumerate(docs):
        out.append({
            "text": doc,
            "metadata": metas[i] if i < len(metas) else {},
            "score": round(1.0 - dists[i], 4) if i < len(dists) else None,
        })
    return out


# ── Memoria semántica de lecciones (F0.2) ─────────────────────────────────────
# Namespace por repo: las lecciones de un repo no contaminan a otro. La escritura
# se cablea en `learning_memory.append_to_lessons` (punto único que cubre A7 y A8);
# la lectura semántica la consumen A4/A5/A7 vía `learning_memory.lessons_for_context`.

def namespace_for(repo_path: str | None) -> str:
    """Namespace de memoria de lecciones derivado del repo (basename, saneado)."""
    from pathlib import Path as _P
    base = _P(repo_path).name if repo_path else "default"
    return f"lessons:{_safe_ns(base)}"


def record_lesson(repo_path: str | None, text: str, metadata: dict | None = None) -> bool:
    """Indexa una lección en la memoria semántica del repo (idempotente por hash del texto)."""
    if not repo_path or not text:
        return False
    return add_memory(namespace_for(repo_path), text, metadata)


def semantic_lessons_block(repo_path: str | None, query_text: str, top_k: int = 5) -> str:
    """
    Bloque markdown con las `top_k` lecciones más similares semánticamente a `query_text`.
    Devuelve "" si no hay coincidencias (p. ej. store frío) — el llamador puede degradar
    al bloque keyword de `load_lessons`.
    """
    if not repo_path or not query_text:
        return ""
    hits = query(namespace_for(repo_path), query_text, top_k=top_k)
    if not hits:
        return ""
    how = "semántica" if backend() == "chromadb" else "keyword"
    block = (
        "\n## ⚠️ LECCIONES APRENDIDAS (memoria " + how + " — más similares a este plan)\n"
        f"_(top {len(hits)} — no repitas estos errores)_\n\n"
    )
    block += "\n".join(f"- {h['text']}" for h in hits) + "\n"
    return block
