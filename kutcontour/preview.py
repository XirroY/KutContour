"""Raster previews: what the PDF will look like, and a design template to draw on."""

from __future__ import annotations

from typing import Sequence

from PIL import Image, ImageDraw

from .geometry import Contour, flatten
from .imaging import PreparedImage
from .layout import ImagePlacement

MAGENTA = (236, 0, 140)


def _to_px(point: tuple[float, float], page_h: float, dpi: float) -> tuple[float, float]:
    """PDF space (y up, mm) -> image space (y down, px)."""
    scale = dpi / 25.4
    return (point[0] * scale, (page_h - point[1]) * scale)


def render_preview(
    contours: Sequence[Contour],
    page_w: float,
    page_h: float,
    image: PreparedImage | None = None,
    placement: ImagePlacement | None = None,
    dpi: float = 72.0,
    line_px: int = 2,
) -> Image.Image:
    scale = dpi / 25.4
    canvas = Image.new("RGB", (max(1, round(page_w * scale)), max(1, round(page_h * scale))), "white")

    if image is not None and placement is not None:
        art = image.image
        if art.mode != "RGB":
            art = art.convert("RGB")
        w = max(1, round(placement.width_mm * scale))
        h = max(1, round(placement.height_mm * scale))
        art = art.resize((w, h), Image.LANCZOS)
        x = round(placement.x_mm * scale)
        y = round((page_h - placement.y_mm - placement.height_mm) * scale)
        canvas.paste(art, (x, y))

    draw = ImageDraw.Draw(canvas)
    for contour in contours:
        pts = [_to_px(p, page_h, dpi) for p in flatten(contour)]
        draw.line(pts, fill=MAGENTA, width=line_px, joint="curve")
    return canvas


def render_template(
    contours: Sequence[Contour],
    page_w: float,
    page_h: float,
    dpi: float = 150.0,
    safe_margin_mm: float = 5.0,
) -> Image.Image:
    """A blank page with the cut line on it, to design artwork against.

    The dashed inner outline marks the safe area: keep text and logos inside it,
    and let background colour run all the way to the page edge.
    """
    scale = dpi / 25.4
    canvas = Image.new("RGB", (round(page_w * scale), round(page_h * scale)), "white")
    draw = ImageDraw.Draw(canvas)

    for contour in contours:
        pts = [_to_px(p, page_h, dpi) for p in flatten(contour)]
        draw.line(pts, fill=MAGENTA, width=max(1, round(dpi / 96)), joint="curve")
        if safe_margin_mm:
            _draw_dashed(draw, _inset(pts, safe_margin_mm * scale), (170, 170, 170))
    return canvas


def _inset(points: Sequence[tuple[float, float]], amount: float) -> list[tuple[float, float]]:
    """Shrink a polyline towards its own centre. Good enough for a visual guide."""
    if not points:
        return []
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        dist = (dx * dx + dy * dy) ** 0.5 or 1.0
        factor = max(0.0, (dist - amount) / dist)
        out.append((cx + dx * factor, cy + dy * factor))
    return out


def _draw_dashed(draw: ImageDraw.ImageDraw, points: Sequence[tuple[float, float]], color, dash: int = 9) -> None:
    for i in range(0, len(points) - 1, 2):
        draw.line([points[i], points[i + 1]], fill=color, width=1)
