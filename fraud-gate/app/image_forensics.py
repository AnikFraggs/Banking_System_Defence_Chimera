from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np


MAX_IMAGE_BYTES = 2_000_000
MAX_IMAGE_PIXELS = 16_000_000


@dataclass(frozen=True)
class ImageForensics:
    fft_artifact_score: float
    metadata: dict[str, str]
    ocr_text: str | None


def frequency_artifact_score(gray: np.ndarray) -> float:
    if gray.ndim != 2 or min(gray.shape, default=0) < 16:
        raise ValueError("image must be a two-dimensional array of at least 16x16 pixels")
    values = np.asarray(gray, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("image pixels must be finite")
    scale = max(float(np.ptp(values)), 1.0)
    values = (values - np.mean(values)) / scale
    window = np.outer(np.hanning(values.shape[0]), np.hanning(values.shape[1]))
    spectrum = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(values * window))))
    center_y, center_x = np.array(spectrum.shape) // 2
    yy, xx = np.indices(spectrum.shape)
    radius = np.sqrt((yy - center_y) ** 2 + (xx - center_x) ** 2)
    low_frequency = radius <= 6
    outer = (radius > 12) & (radius <= min(spectrum.shape) * 0.45)
    baseline = float(np.median(spectrum[outer]))
    mad = float(np.median(np.abs(spectrum[outer] - baseline)))
    threshold = baseline + max(6.0 * mad, 0.25)
    peaks = (spectrum > threshold) & outer & ~low_frequency
    if not peaks.any():
        return 0.0
    peak_energy = float(np.sum(np.maximum(spectrum[peaks] - baseline, 0.0)))
    total_energy = float(np.sum(np.maximum(spectrum[outer] - baseline, 0.0)))
    concentration = peak_energy / max(total_energy, 1e-12)
    peak_density = float(np.count_nonzero(peaks)) / max(int(np.count_nonzero(outer)), 1)
    score = concentration * math.exp(-80.0 * peak_density)
    return float(np.clip(score, 0.0, 0.75))


def screen_image_bytes(
    payload: bytes,
    *,
    ocr: Callable[[object], str] | None = None,
) -> ImageForensics:
    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("image payload must contain 1 to 2000000 bytes")
    if not (
        payload.startswith(b"\x89PNG\r\n\x1a\n")
        or payload.startswith(b"\xff\xd8\xff")
        or (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP")
    ):
        raise ValueError("only PNG, JPEG, and WebP images are accepted")
    try:
        from PIL import ExifTags, Image, UnidentifiedImageError
    except ImportError as error:
        raise RuntimeError("Pillow is required for image forensics") from error

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.verify()
        with Image.open(io.BytesIO(payload)) as source:
            metadata = {}
            exif = source.getexif()
            for key, value in list(exif.items())[:32]:
                name = ExifTags.TAGS.get(key, str(key))
                metadata[str(name)[:64]] = str(value)[:256]
            gray_image = source.convert("L")
            gray_image.thumbnail((512, 512))
            gray = np.asarray(gray_image, dtype=np.float64) / 255.0
            text = ocr(source)[:8192] if ocr else None
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise ValueError("invalid or unsafe image payload") from error
    return ImageForensics(frequency_artifact_score(gray), metadata, text)


def score_image_evidence(forensics: ImageForensics, generator_score: float = 0.0) -> float:
    if not 0.0 <= generator_score <= 1.0:
        raise ValueError("generator score must be between zero and one")
    return max(forensics.fft_artifact_score, generator_score)
