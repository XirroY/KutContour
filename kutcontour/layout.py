"""Where the cut line and the artwork end up on the page (all sizes in mm)."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor
from typing import Sequence

from .geometry import BBox, Contour, contours_bbox

# Defaults for the job this tool was written for.
PAGE_WIDTH_MM = 263.0
PAGE_HEIGHT_MM = 303.0
MAX_CUT_WIDTH_MM = 260.0
MAX_CUT_HEIGHT_MM = 300.0


@dataclass
class CutPlacement:
    contours: list[Contour]
    bbox: BBox
    scale: float
    bleed_mm: tuple[float, float]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImagePlacement:
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    crop_px: tuple[int, int, int, int] | None
    effective_dpi: float
    warnings: list[str] = field(default_factory=list)


def place_cut(
    contours: Sequence[Contour],
    page_w: float = PAGE_WIDTH_MM,
    page_h: float = PAGE_HEIGHT_MM,
    max_w: float = MAX_CUT_WIDTH_MM,
    max_h: float = MAX_CUT_HEIGHT_MM,
    center: bool = True,
    fit: bool = False,
) -> CutPlacement:
    """Scale (optionally) and centre the cut contours on the page.

    With `fit`, geometry larger than the maximum cut size is scaled down to
    fit; without it, an oversized contour is reported as a warning and left
    at its real size, because a silently resized cut file is worse than a
    loud one.
    """
    warnings: list[str] = []
    box = contours_bbox(contours)
    scale = 1.0

    if box.width > max_w + 1e-6 or box.height > max_h + 1e-6:
        if fit:
            scale = min(max_w / box.width, max_h / box.height)
            warnings.append(
                f"cut line was {box.width:.1f} x {box.height:.1f} mm, scaled by "
                f"{scale:.4f} to fit {max_w:g} x {max_h:g} mm"
            )
        else:
            warnings.append(
                f"cut line is {box.width:.1f} x {box.height:.1f} mm, larger than the "
                f"{max_w:g} x {max_h:g} mm maximum (use --fit to scale it down)"
            )

    if center:
        cx, cy = box.center
        dx = page_w / 2 - cx * scale
        dy = page_h / 2 - cy * scale
    else:
        dx = dy = 0.0

    placed = [c.scaled_translated(scale, dx, dy) for c in contours]
    new_box = contours_bbox(placed)

    bleed_x = min(new_box.xmin, page_w - new_box.xmax)
    bleed_y = min(new_box.ymin, page_h - new_box.ymax)
    if bleed_x < -1e-6 or bleed_y < -1e-6:
        warnings.append("cut line falls outside the page")
    elif min(bleed_x, bleed_y) < 1.0:
        warnings.append(
            f"only {min(bleed_x, bleed_y):.2f} mm of bleed around the cut line; "
            "1.5 mm is the usual minimum"
        )

    return CutPlacement(
        contours=placed,
        bbox=new_box,
        scale=scale,
        bleed_mm=(bleed_x, bleed_y),
        warnings=warnings,
    )


def base_size(
    px_width: int,
    px_height: int,
    page_w: float,
    page_h: float,
    fit: str,
) -> tuple[float, float]:
    """The artwork's size at scale 1.0, before any zoom or nudge is applied."""
    page_aspect = page_w / page_h
    img_aspect = px_width / px_height
    if fit == "stretch":
        return page_w, page_h
    if fit == "contain":
        if img_aspect > page_aspect:
            return page_w, page_w / img_aspect
        return page_h * img_aspect, page_h
    if fit == "cover":
        if img_aspect > page_aspect:
            return page_h * img_aspect, page_h
        return page_w, page_w / img_aspect
    raise ValueError(f"unknown fit mode {fit!r}")


def place_image(
    px_width: int,
    px_height: int,
    page_w: float = PAGE_WIDTH_MM,
    page_h: float = PAGE_HEIGHT_MM,
    fit: str = "cover",
    align: str = "center",
    scale: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    min_dpi: float = 150.0,
) -> ImagePlacement:
    """Work out the rectangle (and pixel crop) for artwork placed on the page.

    fit="cover"   fill the page, cropping the overhang (the print-safe default)
    fit="contain" fit the whole image inside the page, leaving white margins
    fit="stretch" distort the image to exactly the page size

    `scale` zooms in or out from there, and `offset_x` / `offset_y` nudge the
    artwork in millimetres (positive y moves it up, as on the PDF page). The
    part that lands outside the page is cropped off in pixels, so moving the
    artwork around never bloats the PDF with unprintable image data.
    """
    warnings: list[str] = []
    if scale <= 0:
        raise ValueError("scale must be greater than zero")

    base_w, base_h = base_size(px_width, px_height, page_w, page_h, fit)
    w = base_w * scale
    h = base_h * scale

    anchor_x = {"left": 0.0, "right": 1.0}.get(align, 0.5)
    anchor_y = {"bottom": 0.0, "top": 1.0}.get(align, 0.5)
    x = (page_w - w) * anchor_x + offset_x
    y = (page_h - h) * anchor_y + offset_y

    # Keep only the part that lands on the page.
    vis_x0, vis_y0 = max(x, 0.0), max(y, 0.0)
    vis_x1, vis_y1 = min(x + w, page_w), min(y + h, page_h)
    if vis_x1 - vis_x0 <= 0 or vis_y1 - vis_y0 <= 0:
        raise ValueError("the artwork has been moved completely off the page")

    crop: tuple[int, int, int, int] | None = None
    if (vis_x1 - vis_x0) < w - 1e-6 or (vis_y1 - vis_y0) < h - 1e-6:
        # Round outwards so a rounded pixel edge never leaves a white sliver.
        left = max(0, floor((vis_x0 - x) / w * px_width))
        right = min(px_width, ceil((vis_x1 - x) / w * px_width))
        # Pixel rows count from the top of the image, page millimetres from the bottom.
        top = max(0, floor((y + h - vis_y1) / h * px_height))
        bottom = min(px_height, ceil((y + h - vis_y0) / h * px_height))
        left, top = min(left, px_width - 1), min(top, px_height - 1)
        right, bottom = max(right, left + 1), max(bottom, top + 1)
        crop = (left, top, right, bottom)
        # Re-derive the rectangle so it matches the pixels that survived.
        x, y = x + left / px_width * w, y + (px_height - bottom) / px_height * h
        w, h = (right - left) / px_width * w, (bottom - top) / px_height * h
        used_px_w, used_px_h = right - left, bottom - top
        dropped = 1 - (used_px_w * used_px_h) / (px_width * px_height)
        if dropped > 0.02:
            warnings.append(f"{dropped * 100:.0f}% of the artwork falls outside the page")
    else:
        used_px_w, used_px_h = px_width, px_height

    uncovered = (
        x > 0.01 or y > 0.01 or x + w < page_w - 0.01 or y + h < page_h - 0.01
    )
    if uncovered:
        warnings.append("artwork does not fill the page; the uncovered edge prints white")

    dpi_x = used_px_w / (w / 25.4) if w else 0.0
    dpi_y = used_px_h / (h / 25.4) if h else 0.0
    dpi = min(dpi_x, dpi_y)
    if dpi < min_dpi:
        warnings.append(
            f"artwork is only {dpi:.0f} dpi at this size; {min_dpi:.0f} dpi is the "
            "practical minimum for print"
        )

    return ImagePlacement(x, y, w, h, crop, dpi, warnings)
