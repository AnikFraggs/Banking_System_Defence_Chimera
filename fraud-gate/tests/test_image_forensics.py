import io

import numpy as np
import pytest

from app.image_forensics import frequency_artifact_score, screen_image_bytes


def test_frequency_score_is_bounded_and_detects_periodic_pattern():
    yy, xx = np.indices((128, 128))
    smooth = np.sin(xx / 30.0) * 0.01
    periodic = ((xx // 4 + yy // 4) % 2).astype(float)
    smooth_score = frequency_artifact_score(smooth)
    periodic_score = frequency_artifact_score(periodic)
    assert 0.0 <= smooth_score <= 0.75
    assert 0.0 <= periodic_score <= 0.75
    assert periodic_score > smooth_score


def test_image_screening_extracts_bounded_signals():
    Image = pytest.importorskip("PIL.Image")
    image = Image.fromarray((((np.indices((64, 64))[1] // 2) % 2) * 255).astype(np.uint8))
    output = io.BytesIO()
    image.save(output, format="PNG")
    result = screen_image_bytes(output.getvalue(), ocr=lambda _: "SIMULATED INVOICE")
    assert 0.0 <= result.fft_artifact_score <= 0.75
    assert result.ocr_text == "SIMULATED INVOICE"


def test_image_screening_rejects_invalid_payload():
    with pytest.raises(ValueError):
        screen_image_bytes(b"not an image")
