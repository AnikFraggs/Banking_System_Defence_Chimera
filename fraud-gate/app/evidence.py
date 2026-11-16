"""Bounded deterministic evidence heuristics with optional local image forensics."""
from __future__ import annotations

import base64
import re

from .image_forensics import score_image_evidence, screen_image_bytes
from .schemas import Evidence


SUSPICIOUS_GENERATORS = (
    "midjourney",
    "dall-e",
    "dalle",
    "stable diffusion",
    "stablediffusion",
    "adobe firefly",
    "comfyui",
    "automatic1111",
    "synthid",
    "photoshop generative",
    "generativeai",
)


def _marker_score(evidence: Evidence) -> float:
    parts = [evidence.generator_marker or "", evidence.ocr_text or ""]
    parts.extend(f"{key} {value}" for key, value in evidence.metadata.items())
    blob = " ".join(parts).lower()
    if any(marker in blob for marker in SUSPICIOUS_GENERATORS):
        return 1.0
    if "ai generated" in blob or "ai-generated" in blob:
        return 0.9
    if evidence.generator_marker:
        # An explicit but unknown generator is a clue, not decisive evidence.
        return 0.55
    return 0.0


def _text_uniformity(text: str | None) -> float:
    if not text or len(text.strip()) < 80:
        return 0.0
    stripped = text.strip()
    printable_share = sum(char.isprintable() for char in stripped) / len(stripped)
    repeated_line = False
    lines = [line.strip() for line in stripped.splitlines() if len(line.strip()) >= 20]
    if lines:
        repeated_line = max(lines.count(line) for line in set(lines)) >= 3

    score = 0.0
    if printable_share > 0.995 and not any(char.isdigit() for char in stripped):
        score += 0.2
    if re.search(r"(.)\1{30,}", stripped):
        score += 0.25
    if repeated_line:
        score += 0.25
    # Clean text alone must not trigger the strong-evidence policy band.
    return min(0.45, score)


def score_evidence(evidence: Evidence | None) -> float:
    if evidence is None:
        return 0.0
    image_score = 0.0
    if evidence.image_payload:
        forensics = screen_image_bytes(base64.b64decode(evidence.image_payload))
        metadata = {**evidence.metadata, **forensics.metadata}
        evidence = evidence.model_copy(update={
            "metadata": metadata,
            "ocr_text": evidence.ocr_text or forensics.ocr_text,
            "image_payload": None,
        })
        image_score = score_image_evidence(forensics)
    residual = evidence.pixel_residual or 0.0
    return max(
        _marker_score(evidence),
        _text_uniformity(evidence.ocr_text),
        residual,
        image_score,
    )
