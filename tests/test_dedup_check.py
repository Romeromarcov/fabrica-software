"""Tests de tools/dedup_check.py — detección determinista de capacidades duplicadas."""
from tools import dedup_check as dc


def test_similarity_identical_and_disjoint():
    assert dc.similarity("Analista de riesgo legal", "Analista de riesgo legal") == 1.0
    assert dc.similarity("optimizador de SEO", "cocinero de paella") == 0.0


def test_similarity_partial_overlap_between_0_and_1():
    s = dc.similarity("Analista de riesgo de contratos", "Analista de cumplimiento de contratos")
    assert 0.0 < s < 1.0


def test_find_similar_agents_flags_overlap():
    agents = [
        {"id": "L1", "role": "Analista de riesgo de contratos", "pipeline": "legal"},
        {"id": "M3", "role": "Diseñador de arte para redes", "pipeline": "marketing"},
    ]
    out = dc.find_similar_agents("Analista de riesgo contractual", agents=agents, threshold=0.3)
    assert out and out[0]["id"] == "L1"
    assert out[0]["score"] >= 0.3
    # El diseñador no se parece → no aparece.
    assert all(m["id"] != "M3" for m in out)


def test_find_similar_agents_empty_when_no_match():
    agents = [{"id": "X", "role": "cosa totalmente distinta", "pipeline": "p"}]
    assert dc.find_similar_agents("optimizador de metadatos seo", agents=agents) == []


def test_find_similar_pipelines_identical_name_is_certain_duplicate():
    summaries = [{"name": "legal", "description": "otra cosa"}]
    out = dc.find_similar_pipelines("legal", "revisa contratos", summaries=summaries)
    assert out and out[0]["name"] == "legal"
    assert out[0]["score"] == 1.0


def test_find_similar_pipelines_by_description_overlap():
    summaries = [{"name": "contratos", "description": "revisa contratos legales y riesgos"}]
    out = dc.find_similar_pipelines("legal", "revisa contratos legales", summaries=summaries,
                                    threshold=0.3)
    assert out and out[0]["name"] == "contratos"
