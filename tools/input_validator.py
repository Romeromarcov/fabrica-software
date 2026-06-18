"""
tools/input_validator.py — Validador de input estilo AIDefence (PLAN_PLATAFORMA_V2 R4, Fase 1).

Se ejecuta sobre el brief del Founder ANTES de A0 para detectar:
  - Inyección de prompt (intentos de secuestrar las instrucciones del sistema).
  - PII (emails, teléfonos, tarjetas, documentos de identidad).
  - Secretos/credenciales (reutiliza los patrones de `log_sanitizer`).

Diseño: lógica pura, sin side effects al importar, offline (sin LLM). Devuelve un
`InputReport` estructurado. El veredicto `block` solo se emite ante inyección de
severidad alta; PII/secretos producen `sanitize` (se redacta, no se bloquea) salvo
configuración estricta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.log_sanitizer import redact

# ── Patrones de inyección de prompt ────────────────────────────────────────────
# Frases que intentan anular/ignorar las instrucciones del sistema o exfiltrar el
# prompt. Bilingüe (es/en) porque el brief del Founder puede venir en cualquiera.
_INJECTION_PATTERNS = [
    r"ignore (all |the |your )?(previous|prior|above) (instructions|prompts?)",
    r"ignora (todas |las |tus )?(instrucciones|indicaciones) (previas|anteriores)",
    r"disregard (all |the )?(previous|above|prior) ",
    r"olvida (todo|las instrucciones)",
    r"you are (now )?(a|an|in) (developer|dan|jailbreak|admin) mode",
    r"act as (if you are )?(an? )?(unrestricted|jailbroken|dan)\b",
    r"reveal (your |the )?(system )?(prompt|instructions)",
    r"(muestra|revela|imprime) (tu |el )?(system ?)?(prompt|instrucciones del sistema)",
    r"\boverride\b.{0,20}\b(safety|guardrails?|rules?)\b",
    r"\b(sudo|root)\b.{0,15}\b(mode|access|prompt)\b",
    r"pretend (you|to) (are|be) ",
    r"bypass (all |any )?(restrictions?|filters?|safety)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]

# ── Patrones de PII ────────────────────────────────────────────────────────────
_PII_PATTERNS = {
    "email":       re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "phone":       re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?!\d)"),
}


@dataclass
class InputReport:
    verdict: str                       # "allow" | "sanitize" | "block"
    injection_findings: list[str] = field(default_factory=list)
    pii_findings: list[str] = field(default_factory=list)
    secret_findings: bool = False
    sanitized_text: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict != "block"


def detect_prompt_injection(text: str) -> list[str]:
    """Devuelve las frases sospechosas de inyección de prompt encontradas."""
    findings: list[str] = []
    for rgx in _INJECTION_RE:
        m = rgx.search(text or "")
        if m:
            findings.append(m.group(0).strip())
    return findings


def detect_pii(text: str) -> list[str]:
    """Devuelve etiquetas de los tipos de PII detectados (sin exponer el dato)."""
    found: list[str] = []
    for label, rgx in _PII_PATTERNS.items():
        matches = [m for m in rgx.findall(text or "")]
        # credit_card/phone comparten dígitos: exige longitud mínima real
        if label == "credit_card":
            digits = [re.sub(r"\D", "", m if isinstance(m, str) else "") for m in rgx.findall(text or "")]
            if any(13 <= len(d) <= 16 for d in digits):
                found.append(label)
        elif matches:
            found.append(label)
    return found


def detect_secrets(text: str) -> bool:
    """True si `log_sanitizer.redact` cambió el texto (encontró un secreto)."""
    return redact(text or "") != (text or "")


def validate_input(text: str, strict: bool = False) -> InputReport:
    """
    Valida el brief de entrada.

    - Inyección de prompt → `block` (alta severidad: secuestra al pipeline).
    - PII o secretos → `sanitize` (se redacta y se sigue), o `block` si `strict`.
    - Sin hallazgos → `allow`.

    `sanitized_text` siempre trae el texto con secretos redactados.
    """
    text = text or ""
    injection = detect_prompt_injection(text)
    pii = detect_pii(text)
    secrets = detect_secrets(text)

    sanitized = redact(text)

    if injection:
        verdict = "block"
    elif (pii or secrets):
        verdict = "block" if strict else "sanitize"
    else:
        verdict = "allow"

    return InputReport(
        verdict=verdict,
        injection_findings=injection,
        pii_findings=pii,
        secret_findings=secrets,
        sanitized_text=sanitized,
    )


def neutralize(text: str) -> str:
    """
    Devuelve el texto con las frases de inyección de prompt eliminadas y los
    secretos redactados — apto para entregárselo al LLM sin que la inyección
    llegue al modelo. No bloquea: neutraliza.
    """
    cleaned = text or ""
    for rgx in _INJECTION_RE:
        cleaned = rgx.sub("[contenido removido por seguridad]", cleaned)
    return redact(cleaned)


def guard_brief(brief: str, strict: bool = False) -> tuple[str, InputReport]:
    """
    Helper de integración para A0: valida el brief del Founder y devuelve
    `(brief_seguro, report)`. El brief seguro tiene la inyección neutralizada y
    los secretos redactados; el report lleva los hallazgos para observabilidad.
    """
    report = validate_input(brief, strict=strict)
    safe = neutralize(brief) if (report.injection_findings or report.secret_findings) else brief
    return safe, report
