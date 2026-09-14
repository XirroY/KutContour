"""Where the cut line and the artwork end up on the page (all sizes in mm)."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def place_image(
    px_width: int,
    px_height: int,
    page_w: float = PAGE_WIDTH_MM,
    page_h: float = PAGE_HEIGHT_MM,
    fit: str = "cover",
    align: str = "center",
    min_dpi: float = 150.0,
) -> ImagePlacement:
    """Work out the rectangle (and crop) for artwork placed on the page.

    fit="cover"   fill the page, cropping the overhang (the print-safe default)
    fit="contain" fit the whole image inside the page, leaving white margins
    fit="stretch" distort the image to exactly the page size
    """
    warnings: list[str] = []
    page_aspect = page_w / page_h
    img_aspect = px_width / px_height
    crop: tuple[int, int, int, int] | None = None

    if fit == "stretch":
        x, y, w, h = 0.0, 0.0, page_w, page_h
        used_px_w, used_px_h = px_width, px_height
    elif fit == "contain":
        if img_aspect > page_aspect:
            w = page_w
            h = page_w / img_aspect
        else:
            h = page_h
            w = page_h * img_aspect
        x = (page_w - w) / 2
        y = (page_h - h) / 2
        used_px_w, used_px_h = px_width, px_height
        if w < page_w - 0.01 or h < page_h - 0.01:
            warnings.append(
                "artwork does not fill the page; the uncovered edge prints white"
            )
    elif fit == "cover":
        if img_aspect > page_aspect:
            crop_w = int(round(px_height * page_aspect))
            crop_h = px_height
        else:
            crop_w = px_width
            crop_h = int(round(px_width / page_aspect))
        crop_w = min(crop_w, px_width)
        crop_h = min(crop_h, px_height)
        left = {"left": 0, "right": px_width - crop_w}.get(align, (px_width - crop_w) // 2)
        # PIL boxes count from the top, so "top" means offset 0.
        top = {"top": 0, "bottom": px_height - crop_h}.get(align, (px_height - crop_h) // 2)
        crop = (left, top, left + crop_w, top + crop_h)
        x, y, w, h = 0.0, 0.0, page_w, page_h
        used_px_w, used_px_h = crop_w, crop_h
        dropped = 1 - (crop_w * crop_h) / (px_width * px_height)
        if dropped > 0.02:
            warnings.append(f"{dropped * 100:.0f}% of the artwork is cropped away to fill the page")
    else:
        raise ValueError(f"unknown fit mode {fit!r}")

    dpi_x = used_px_w / (w / 25.4) if w else 0.0
    dpi_y = used_px_h / (h / 25.4) if h else 0.0
    dpi = min(dpi_x, dpi_y)
    if dpi < min_dpi:
        warnings.append(
            f"artwork is only {dpi:.0f} dpi at this size; {min_dpi:.0f} dpi is the "
            "practical minimum for print"
        )

    return ImagePlacement(x, y, w, h, crop, dpi, warnings)
