import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.make_sample_dxf import build as build_sample_dxf  # noqa: E402


@pytest.fixture
def sample_dxf(tmp_path) -> str:
    path = tmp_path / "sample.dxf"
    build_sample_dxf(str(path))
    return str(path)


@pytest.fixture
def artwork(tmp_path) -> str:
    """A 3:2 landscape image, deliberately the wrong shape for the portrait page."""
    img = Image.new("RGB", (1200, 800), "#1a4f8a")
    ImageDraw.Draw(img).ellipse([400, 200, 800, 600], fill="#e03030")
    path = tmp_path / "art.png"
    img.save(path)
    return str(path)
