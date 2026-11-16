"""Redis-backed graph-augmented archetype memory for asynchronous feedback."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import struct
import zlib
from collections.abc import Mapping
from typing import Any, Literal

from .canonical import Scalar, canonicalize_telemetry, normalize_telemetry
from .case_matching import (
    HASHED_MODEL,
    MAX_CANDIDATES,
    CaseCandidate,
    CaseMatcher,
    CaseSearchResult,
    HashedCaseMatcher,
    hashed_vector,
    query_text,
    structured_feature_similarity,
)

logger = logging.getLogger(__name__)
Verdict = Literal["FRAUD", "BENIGN", "INCONCLUSIVE"]
_VECTOR_BYTES = 128 * 4
_UPDATE_SCRIPT = """
if redis.call('EXISTS', KEYS[3]) == 1 then return -1 end
local current = redis.call('HGET', KEYS[1], 'version')
if ARGV[1] == '0' then
  if current then return 0 end
else
  if not current or tostring(current) ~= ARGV[1] then return 0 end
end
redis.call('HSET', KEYS[1], unpack(ARGV, 4))
redis.call('ZADD', KEYS[2], 0, ARGV[2])
redis.call('SET', KEYS[3], ARGV[3])
return 1
"""


class SettledOrderError(RuntimeError):
    """An analyst verdict for this order has already been consumed."""


def compress_vector(vector: tuple[float, ...]) -> str:
    if len(vector) != 128 or any(not math.isfinite(value) for value in vector):
        raise ValueError("memory vectors must contain 128 finite values")
    packed = struct.pack("<128f", *vector)
    return base64.b64encode(zlib.compress(packed, level=9)).decode("ascii")


def decompress_vector(value: str | bytes) -> tuple[float, ...]:
    try:
        compressed = base64.b64decode(value, validate=True)
        decompressor = zlib.decompressobj()
        packed = decompressor.decompress(compressed, _VECTOR_BYTES + 1)
        if len(packed) != _VECTOR_BYTES or decompressor.unconsumed_tail:
            raise ValueError("invalid compressed vector length")
        vector = struct.unpack("<128f", packed)
    except (ValueError, zlib.error, struct.error) as exc:
        raise ValueError("invalid compressed memory vector") from exc
    if any(not math.isfinite(item) for item in vector):
        raise ValueError("memory vectors must be finite")
    return tuple(float(item) for item in vector)


def _key(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _hash_fields(fields: Mapping[Any, Any]) -> dict[str, str]:
    return {_key(key): _key(value) for key, value in fields.items()}


_LSH_BANDS = 12
_LSH_BITS = 8


def lsh_bucket_keys(vector: tuple[float, ...], *, bands: int = _LSH_BANDS, bits: int = _LSH_BITS) -> tuple[str, ...]:
    """Sign-random-projection buckets over the 128-dim hashed vectors (fixed seed, no numpy).

    Deterministic hash-generated hyperplanes make bucket membership reproducible across
    processes, so a stored archetype and a later query land in the same buckets.
    """
    keys = []
    for band in range(bands):
        code = 0
        for bit in range(bits):
            generator = hashlib.shake_128(f"chimera-lsh-v1:{band}:{bit}".encode("ascii"))
            plane = struct.unpack("<128b", generator.digest(128))
            projection = sum(weight * value for weight, value in zip(plane, vector))
            code = (code << 1) | (1 if projection >= 0 else 0)
        keys.append(f"{band}:{code:0{(bits + 3) // 4}x}")
    return tuple(keys)


def _centroid_features(
    old: Mapping[str, Scalar], new: Mapping[str, Scalar], count: int
) -> dict[str, Scalar]:
    merged: dict[str, Scalar] = dict(old)
    for key, value in new.items():
        previous = old.get(key)
        if (
            isinstance(previous, (int, float)) and not isinstance(previous, bool)
            and isinstance(value, (int, float)) and not isinstance(value, bool)
        ):
            merged[key] = (float(previous) * count + float(value)) / (count + 1)
        elif isinstance(previous, bool) and isinstance(value, bool):
            # Ties retain the previous centroid value deterministically.
            merged[key] = previous if previous == value else count >= 1
        elif previous is None or previous == value:
            merged[key] = value
    return normalize_telemetry(merged)


class RedisCaseMemory:
    """Historical centroids with immutable per-order feedback consumption.

    Archetype records are separate from per-order settlement markers. The Lua
    compare-and-set ensures a duplicate verdict cannot mutate a centroid, while
    the version check prevents concurrent new orders from losing updates.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        matcher: CaseMatcher | None = None,
        prefix: str = "fraud-gate:case-memory",
        candidate_strategy: str = "lsh",
    ) -> None:
        if candidate_strategy not in ("lsh", "first_page"):
            raise ValueError("candidate_strategy must be 'lsh' or 'first_page'")
        self.redis = redis_client
        self.matcher = matcher or HashedCaseMatcher()
        self.prefix = prefix.rstrip(":")
        self.index_key = f"{self.prefix}:archetypes"
        self.candidate_strategy = candidate_strategy

    def _case_key(self, case_id: str) -> str:
        return f"{self.prefix}:archetype:{case_id}"

    def _settled_key(self, order_id: str) -> str:
        return f"{self.prefix}:settled-order:{order_id}"

    def _graph_key(self, case_id: str) -> str:
        return f"{self.prefix}:graph:{case_id}"

    def _bucket_key(self, signature: str) -> str:
        return f"{self.prefix}:bucket:{signature}"

    async def _update_buckets(self, case_id: str, vector: tuple[float, ...]) -> None:
        signatures = set(lsh_bucket_keys(vector))
        member_key = f"{self.prefix}:buckets:{case_id}"
        raw_old = await self.redis.smembers(member_key)
        old = {_key(item) for item in raw_old}
        stale, fresh = sorted(old - signatures), sorted(signatures - old)
        if stale or fresh:
            pipe = self.redis.pipeline()
            for signature in stale:
                pipe.srem(self._bucket_key(signature), case_id)
            for signature in fresh:
                pipe.sadd(self._bucket_key(signature), case_id)
            if stale:
                pipe.srem(member_key, *stale)
            if fresh:
                pipe.sadd(member_key, *fresh)
            await pipe.execute()

    async def rebuild_buckets(self, limit: int = 100_000) -> int:
        """One-shot backfill of bucket membership for archetypes written before indexing."""
        raw_ids = await self.redis.zrange(self.index_key, 0, limit - 1)
        count = 0
        for raw_id in raw_ids:
            case_id = _key(raw_id)
            fields = _hash_fields(await self.redis.hgetall(self._case_key(case_id)))
            if not fields:
                continue
            await self._update_buckets(case_id, decompress_vector(fields["vector"]))
            count += 1
        return count

    async def _candidate_ids(self, vector: tuple[float, ...], limit: int) -> list[str]:
        """Collision-count ranked candidates from the LSH buckets; fills from the index page."""
        if self.candidate_strategy == "first_page":
            raw_ids = await self.redis.zrange(self.index_key, 0, limit - 1)
            return [_key(item) for item in raw_ids]
        buckets = [self._bucket_key(signature) for signature in lsh_bucket_keys(vector)]
        members = await asyncio.gather(*(self.redis.smembers(key) for key in buckets))
        hits: dict[str, int] = {}
        for bucket in members:
            for raw_id in bucket:
                case_id = _key(raw_id)
                hits[case_id] = hits.get(case_id, 0) + 1
        ranked = sorted(hits, key=lambda case_id: (-hits[case_id], case_id))[:limit]
        if len(ranked) < limit:
            chosen = set(ranked)
            raw_ids = await self.redis.zrange(self.index_key, 0, limit - 1)
            for raw_id in raw_ids:
                case_id = _key(raw_id)
                if case_id not in chosen:
                    ranked.append(case_id)
                    if len(ranked) >= limit:
                        break
        return ranked

    async def update_from_analyst_verdict(
        self,
        *,
        order_id: str,
        decision_id: str,
        verdict: Verdict,
        telemetry: Mapping[str, Any],
        text: str = "",
        archetype_id: str | None = None,
    ) -> str:
        """Consume one final analyst verdict and update a historical centroid.

        Reusing an already consumed ``order_id`` raises ``SettledOrderError``
        before any archetype or graph write. No pre-capture decision is read or
        changed by this method.
        """
        order_id = order_id.strip()
        decision_id = decision_id.strip()
        if not order_id or len(order_id) > 128:
            raise ValueError("a bounded order_id is required for verdict feedback")
        if not decision_id or len(decision_id) > 128:
            raise ValueError("a bounded decision_id is required for verdict feedback")
        if verdict not in {"FRAUD", "BENIGN", "INCONCLUSIVE"}:
            raise ValueError("unsupported analyst verdict")
        features = normalize_telemetry(telemetry)
        canonical = canonicalize_telemetry(features)
        case_id = archetype_id or "arch_" + hashlib.sha256(
            f"{verdict}|{canonical}".encode("utf-8")
        ).hexdigest()[:24]
        if not case_id or len(case_id) > 128 or any(char.isspace() for char in case_id):
            raise ValueError("archetype_id must be a bounded token")
        case_key = self._case_key(case_id)
        vector = hashed_vector(query_text(text, features))

        for _attempt in range(4):
            raw_existing = await self.redis.hgetall(case_key)
            existing = _hash_fields(raw_existing)
            expected_version = int(existing.get("version", "0"))
            sample_count = int(existing.get("sample_count", "0"))
            if existing and existing.get("verdict") != verdict:
                raise ValueError("an archetype cannot change analyst verdict")
            if existing:
                old_features = normalize_telemetry(json.loads(existing["features"]))
                old_vector = decompress_vector(existing["vector"])
                merged_vector = tuple(
                    (old * sample_count + new) / (sample_count + 1)
                    for old, new in zip(old_vector, vector)
                )
                merged_features = _centroid_features(old_features, features, sample_count)
            else:
                merged_vector = vector
                merged_features = features
            fields = {
                "case_id": case_id,
                "verdict": verdict,
                "text": query_text(text, merged_features)[:2048],
                "features": json.dumps(merged_features, sort_keys=True, separators=(",", ":")),
                "vector": compress_vector(merged_vector),
                "vector_model": HASHED_MODEL,
                "sample_count": str(sample_count + 1),
                "version": str(expected_version + 1),
            }
            arguments = [str(expected_version), case_id, decision_id]
            for field, value in fields.items():
                arguments.extend((field, value))
            status = int(await self.redis.eval(
                _UPDATE_SCRIPT,
                3,
                case_key,
                self.index_key,
                self._settled_key(order_id),
                *arguments,
            ))
            if status == -1:
                raise SettledOrderError(f"order {order_id} already has a settled verdict")
            if status == 0:
                continue
            if status != 1:
                raise RuntimeError("unexpected Redis verdict-update response")
            try:
                await self._update_graph(case_id, merged_features)
            except Exception as exc:
                # The verdict and centroid are durable; graph hints can be rebuilt.
                logger.warning("Could not update case-memory graph for %s: %s", case_id, exc)
            try:
                await self._update_buckets(case_id, merged_vector)
            except Exception as exc:
                # Bucket hints can be rebuilt with rebuild_buckets(); the centroid stays durable.
                logger.warning("Could not update case-memory buckets for %s: %s", case_id, exc)
            return case_id
        raise RuntimeError("concurrent case-memory updates did not converge")

    async def _load_candidate(self, case_id: str) -> CaseCandidate | None:
        raw, raw_related = await asyncio.gather(
            self.redis.hgetall(self._case_key(case_id)),
            self.redis.zrevrange(self._graph_key(case_id), 0, 2),
        )
        fields = _hash_fields(raw)
        if not fields:
            return None
        verdict = fields.get("verdict")
        if verdict not in {"FRAUD", "BENIGN", "INCONCLUSIVE"}:
            logger.warning("Ignoring case-memory record with invalid verdict: %s", case_id)
            return None
        return CaseCandidate(
            case_id=case_id,
            text=fields["text"],
            features=normalize_telemetry(json.loads(fields["features"])),
            verdict=verdict,
            vector=decompress_vector(fields["vector"]),
            vector_model=fields.get("vector_model"),
            related_cases=tuple(_key(item) for item in raw_related[:3]),
        )

    async def _update_graph(
        self, case_id: str, features: Mapping[str, Scalar]
    ) -> None:
        raw_ids = await self.redis.zrange(self.index_key, 0, 63)
        other_ids = [_key(item) for item in raw_ids if _key(item) != case_id]
        candidates = await asyncio.gather(
            *(self._load_candidate(other_id) for other_id in other_ids)
        )
        similarities: list[tuple[float, str]] = []
        for candidate in candidates:
            if candidate is None:
                continue
            similarity = structured_feature_similarity(features, candidate.features)
            if similarity is not None and similarity > 0:
                similarities.append((similarity, candidate.case_id))
        similarities.sort(key=lambda item: (-item[0], item[1]))
        for similarity, other_id in similarities[:3]:
            await asyncio.gather(
                self.redis.zadd(self._graph_key(case_id), {other_id: similarity}),
                self.redis.zadd(self._graph_key(other_id), {case_id: similarity}),
            )
            await asyncio.gather(
                self.redis.zremrangebyrank(self._graph_key(case_id), 0, -4),
                self.redis.zremrangebyrank(self._graph_key(other_id), 0, -4),
            )

    async def match(
        self,
        text: str,
        features: Mapping[str, Any],
        *,
        limit: int = 5,
    ) -> CaseSearchResult:
        """Retrieve bounded candidates (LSH buckets by default), then asynchronously rank."""
        normalized = normalize_telemetry(features)
        ids = await self._candidate_ids(hashed_vector(text), MAX_CANDIDATES)
        loaded = await asyncio.gather(*(self._load_candidate(case_id) for case_id in ids))
        candidates = [candidate for candidate in loaded if candidate is not None]
        return await self.matcher.match(text, normalized, candidates, limit=limit)
