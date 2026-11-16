"""Bounded asynchronous case matching with explicit local/model backends."""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .canonical import Scalar, canonicalize_telemetry

HASHED_MODEL = "sha256-bow-128-v1"
MAX_CANDIDATES = 128
MAX_MATCHES = 10


class MatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CaseMatch(MatchModel):
    case_id: str = Field(min_length=1, max_length=128)
    verdict: Literal["FRAUD", "BENIGN", "INCONCLUSIVE"] | None = None
    score: float = Field(ge=0, le=1)
    text_similarity: float = Field(ge=0, le=1)
    feature_similarity: float | None = Field(default=None, ge=0, le=1)
    model: str = Field(min_length=1, max_length=256)
    related_cases: list[str] = Field(default_factory=list, max_length=3)


class RetrievalMetadata(MatchModel):
    backend: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    bi_encoder: str | None = Field(default=None, max_length=256)
    cross_encoder: str | None = Field(default=None, max_length=256)
    fallback: bool
    candidates_considered: int = Field(ge=0, le=MAX_CANDIDATES)
    truncated: bool = False
    error: str | None = Field(default=None, max_length=256)


class CaseSearchResult(MatchModel):
    matches: list[CaseMatch] = Field(default_factory=list, max_length=MAX_MATCHES)
    retrieval: RetrievalMetadata


@dataclass(frozen=True)
class CaseCandidate:
    case_id: str
    text: str
    features: Mapping[str, Scalar]
    verdict: Literal["FRAUD", "BENIGN", "INCONCLUSIVE"] | None = None
    vector: tuple[float, ...] | None = None
    vector_model: str | None = None
    related_cases: tuple[str, ...] = field(default_factory=tuple)


def empty_search_result(
    *, error: str | None = None, model: str = "disabled"
) -> CaseSearchResult:
    return CaseSearchResult(
        matches=[],
        retrieval=RetrievalMetadata(
            backend="disabled" if error is None else "error",
            model=model,
            fallback=True,
            candidates_considered=0,
            error=error,
        ),
    )


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_MATCHES:
        raise ValueError(f"limit must be between 1 and {MAX_MATCHES}")
    return limit


def hashed_vector(text: str, dimensions: int = 128) -> tuple[float, ...]:
    """Deterministic signed feature hashing; independent of Python hash seeds."""
    if dimensions != 128:
        raise ValueError("the persisted local vector format has 128 dimensions")
    vector = [0.0] * dimensions
    for token in re.findall(r"[\w.-]+", text.lower(), flags=re.UNICODE)[:2048]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return tuple(vector)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    similarity = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return max(0.0, min(1.0, similarity))


def structured_feature_similarity(
    left: Mapping[str, Scalar], right: Mapping[str, Scalar]
) -> float | None:
    """Compare only shared structured keys; no key means no fabricated score."""
    shared = sorted(set(left).intersection(right))
    if not shared:
        return None
    similarities: list[float] = []
    for key in shared:
        first, second = left[key], right[key]
        if first is None or second is None:
            similarities.append(float(first is second))
        elif isinstance(first, bool) or isinstance(second, bool):
            similarities.append(float(type(first) is type(second) and first == second))
        elif isinstance(first, (int, float)) and isinstance(second, (int, float)):
            a, b = float(first), float(second)
            if not math.isfinite(a) or not math.isfinite(b):
                continue
            similarities.append(max(0.0, 1.0 - abs(a - b) / max(1.0, abs(a), abs(b))))
        else:
            similarities.append(float(str(first) == str(second)))
    return sum(similarities) / len(similarities) if similarities else None


class CaseMatcher(ABC):
    """Async-only ranker; implementations bound candidate and result counts."""

    @abstractmethod
    async def match(
        self,
        query_text: str,
        query_features: Mapping[str, Scalar],
        candidates: Sequence[CaseCandidate],
        *,
        limit: int = 5,
    ) -> CaseSearchResult:
        raise NotImplementedError


class HashedCaseMatcher(CaseMatcher):
    """Offline deterministic vector matching plus structured feature reranking."""

    async def match(
        self,
        query_text: str,
        query_features: Mapping[str, Scalar],
        candidates: Sequence[CaseCandidate],
        *,
        limit: int = 5,
    ) -> CaseSearchResult:
        result_limit = _limit(limit)
        bounded = list(candidates[:MAX_CANDIDATES])
        query_vector = hashed_vector(query_text)
        ranked: list[tuple[float, CaseCandidate, float, float | None]] = []
        for candidate in bounded:
            vector = (
                candidate.vector
                if candidate.vector is not None and candidate.vector_model == HASHED_MODEL
                else hashed_vector(candidate.text)
            )
            text_similarity = _cosine(query_vector, vector)
            feature_similarity = structured_feature_similarity(
                query_features, candidate.features
            )
            score = (
                0.75 * text_similarity + 0.25 * feature_similarity
                if feature_similarity is not None
                else text_similarity
            )
            ranked.append((score, candidate, text_similarity, feature_similarity))
        ranked.sort(key=lambda item: (-item[0], item[1].case_id))
        matches = [
            CaseMatch(
                case_id=candidate.case_id,
                verdict=candidate.verdict,
                score=round(score, 6),
                text_similarity=round(text_similarity, 6),
                feature_similarity=(
                    round(feature_similarity, 6)
                    if feature_similarity is not None
                    else None
                ),
                model=HASHED_MODEL,
                related_cases=list(candidate.related_cases[:3]),
            )
            for score, candidate, text_similarity, feature_similarity in ranked[:result_limit]
        ]
        return CaseSearchResult(
            matches=matches,
            retrieval=RetrievalMetadata(
                backend="deterministic_hashed",
                model=HASHED_MODEL,
                bi_encoder=HASHED_MODEL,
                cross_encoder=None,
                fallback=True,
                candidates_considered=len(bounded),
                truncated=len(candidates) > len(bounded),
            ),
        )


class SentenceTransformerCaseMatcher(CaseMatcher):
    """Explicitly configured bi-encoder retrieval and cross-encoder reranking.

    Model downloads/loading happen only when this class is instantiated. Blocking
    inference is moved off the event loop with ``asyncio.to_thread``. Candidate
    embeddings are cached by SHA-256 of their text (bounded LRU), and only the
    bi-encoder top ``rerank_top_k`` candidates are sent to the cross-encoder.
    """

    def __init__(
        self,
        bi_encoder_model: str,
        cross_encoder_model: str,
        *,
        embedding_cache_size: int = 4096,
        rerank_top_k: int = 20,
        bi_encoder: Any | None = None,
        cross_encoder: Any | None = None,
    ) -> None:
        if not bi_encoder_model.strip() or not cross_encoder_model.strip():
            raise ValueError("both sentence-transformer model names are required")
        if not 0 <= embedding_cache_size <= 100_000:
            raise ValueError("embedding_cache_size must be between 0 and 100000")
        if not MAX_MATCHES <= rerank_top_k <= MAX_CANDIDATES:
            raise ValueError(f"rerank_top_k must be between {MAX_MATCHES} and {MAX_CANDIDATES}")
        self.bi_encoder_model = bi_encoder_model
        self.cross_encoder_model = cross_encoder_model
        self.embedding_cache_size = embedding_cache_size
        self.rerank_top_k = rerank_top_k
        self._embeddings: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self.cache_hits = 0
        self.cache_misses = 0
        if bi_encoder is None or cross_encoder is None:
            from sentence_transformers import CrossEncoder, SentenceTransformer

            bi_encoder = bi_encoder or SentenceTransformer(bi_encoder_model)
            cross_encoder = cross_encoder or CrossEncoder(cross_encoder_model)
        self._bi_encoder = bi_encoder
        self._cross_encoder = cross_encoder

    def _encode(self, texts: list[str]) -> list[list[float]]:
        encoded = self._bi_encoder.encode(
            texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
        )
        return [list(map(float, row)) for row in encoded.tolist()]

    def _candidate_vectors(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        with self._lock:
            known = {key: self._embeddings[key] for key in keys if key in self._embeddings}
        missing = [index for index, key in enumerate(keys) if key not in known]
        fresh = self._encode([texts[index] for index in missing]) if missing else []
        vectors: list[list[float] | None] = [known.get(key) for key in keys]
        for index, vector in zip(missing, fresh):
            vectors[index] = vector
        with self._lock:
            self.cache_hits += len(keys) - len(missing)
            self.cache_misses += len(missing)
            if self.embedding_cache_size:
                for key, vector in zip(keys, vectors):
                    self._embeddings[key] = vector  # type: ignore[assignment]
                    self._embeddings.move_to_end(key)
                while len(self._embeddings) > self.embedding_cache_size:
                    self._embeddings.popitem(last=False)
        return [vector for vector in vectors if vector is not None]

    async def match(
        self,
        query_text: str,
        query_features: Mapping[str, Scalar],
        candidates: Sequence[CaseCandidate],
        *,
        limit: int = 5,
    ) -> CaseSearchResult:
        result_limit = _limit(limit)
        bounded = list(candidates[:MAX_CANDIDATES])
        if not bounded:
            return self._result([], 0, False)
        query_vector = (await asyncio.to_thread(self._encode, [query_text]))[0]
        vectors = await asyncio.to_thread(
            self._candidate_vectors, [candidate.text for candidate in bounded]
        )
        bi_scored = sorted(
            (
                ((_cosine(query_vector, vector) + 1.0) / 2.0, index)
                for index, vector in enumerate(vectors)
            ),
            key=lambda item: (-item[0], bounded[item[1]].case_id),
        )[: self.rerank_top_k]
        pairs = [(query_text, bounded[index].text) for _, index in bi_scored]
        raw_cross_scores = await asyncio.to_thread(
            lambda: self._cross_encoder.predict(pairs, batch_size=32, show_progress_bar=False)
        )
        cross_scores = raw_cross_scores.tolist()
        ranked: list[tuple[float, CaseCandidate, float, float | None]] = []
        for (bi_similarity, index), raw_score in zip(bi_scored, cross_scores):
            candidate = bounded[index]
            if isinstance(raw_score, list):
                raw_score = raw_score[1] - raw_score[0]
            cross_similarity = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, float(raw_score)))))
            feature_similarity = structured_feature_similarity(
                query_features, candidate.features
            )
            score = (
                0.55 * bi_similarity + 0.35 * cross_similarity + 0.10 * feature_similarity
                if feature_similarity is not None
                else 0.65 * bi_similarity + 0.35 * cross_similarity
            )
            ranked.append((score, candidate, bi_similarity, feature_similarity))
        ranked.sort(key=lambda item: (-item[0], item[1].case_id))
        matches = [
            CaseMatch(
                case_id=candidate.case_id,
                verdict=candidate.verdict,
                score=round(score, 6),
                text_similarity=round(text_similarity, 6),
                feature_similarity=(
                    round(feature_similarity, 6)
                    if feature_similarity is not None
                    else None
                ),
                model=f"{self.bi_encoder_model}+{self.cross_encoder_model}",
                related_cases=list(candidate.related_cases[:3]),
            )
            for score, candidate, text_similarity, feature_similarity in ranked[:result_limit]
        ]
        return self._result(matches, len(bounded), len(candidates) > len(bounded))

    def _result(
        self, matches: list[CaseMatch], considered: int, truncated: bool
    ) -> CaseSearchResult:
        return CaseSearchResult(
            matches=matches,
            retrieval=RetrievalMetadata(
                backend="sentence_transformers",
                model=f"{self.bi_encoder_model}+{self.cross_encoder_model}",
                bi_encoder=self.bi_encoder_model,
                cross_encoder=self.cross_encoder_model,
                fallback=False,
                candidates_considered=considered,
                truncated=truncated,
            ),
        )


def matcher_from_environment() -> CaseMatcher:
    """Use neural models only when both model names are explicitly configured."""
    bi_encoder = os.environ.get("CASE_BI_ENCODER_MODEL", "").strip()
    cross_encoder = os.environ.get("CASE_CROSS_ENCODER_MODEL", "").strip()
    if bi_encoder or cross_encoder:
        if not bi_encoder or not cross_encoder:
            raise ValueError(
                "CASE_BI_ENCODER_MODEL and CASE_CROSS_ENCODER_MODEL must be set together"
            )
        return SentenceTransformerCaseMatcher(
            bi_encoder,
            cross_encoder,
            embedding_cache_size=int(os.environ.get("CASE_EMBEDDING_CACHE_SIZE", "4096")),
            rerank_top_k=int(os.environ.get("CASE_RERANK_TOP_K", "20")),
        )
    return HashedCaseMatcher()


def query_text(text: str, features: Mapping[str, Scalar]) -> str:
    return f"{canonicalize_telemetry(features)} {text}".strip()[:4096]
