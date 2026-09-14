"""The one job this tool does: DXF + artwork -> print-ready PDF with a cut line."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from PIL import Image

from . import imaging, preview
from .dxfread import read_dxf
from .geometry import Contour
from .imaging import PreparedImage, prepare_image
from .layout import (
    MAX_CUT_HEIGHT_MM,
    MAX_CUT_WIDTH_MM,
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    ImagePlacement,
    place_cut,
    place_image,
)
from .pdfwriter import DEFAULT_STROKE_PT, SPOT_CMYK, SPOT_NAME, PdfOptions, write_pdf


@dataclass
class JobOptions:
    page_w: float = PAGE_WIDTH_MM
    page_h: float = PAGE_HEIGHT_MM
    max_cut_w: float = MAX_CUT_WIDTH_MM
    max_cut_h: float = MAX_CUT_HEIGHT_MM
    units: str | None = None
    layers: Sequence[str] | None = None
    center: bool = True
    fit_cut: bool = False
    image_fit: str = "cover"
    image_align: str = "center"
    to_cmyk: bool = False
    max_dpi: float = 600.0
    min_dpi: float = 150.0
    jpeg_quality: int | None = 92
    stroke_pt: float = DEFAULT_STROKE_PT
    spot_name: str = SPOT_NAME
    spot_cmyk: tuple[float, float, float, float] = SPOT_CMYK
    overprint: bool = True
    pdf_layers: bool = True
    title: str = "KutContour cut file"


@dataclass
class JobResult:
    pdf_path: str
    contours: list[Contour]
    image_placement: ImagePlacement | None
    prepared_image: PreparedImage | None
    warnings: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


def build_pdf(dxf_path: str, image_path: str | None, out_path: str, opts: JobOptions) -> JobResult:
    """Read the cut file, place the artwork under it and write the PDF."""
    warnings: list[str] = []

    dxf = read_dxf(dxf_path, units=opts.units, layers=opts.layers)
    warnings.extend(dxf.warnings)

    cut = place_cut(
        dxf.contours,
        page_w=opts.page_w,
        page_h=opts.page_h,
        max_w=opts.max_cut_w,
        max_h=opts.max_cut_h,
        center=opts.center,
        fit=opts.fit_cut,
    )
    warnings.extend(cut.warnings)

    placement: ImagePlacement | None = None
    prepared: PreparedImage | None = None
    if image_path:
        with Image.open(image_path) as probe:
            px_w, px_h = probe.size
        placement = place_image(
            px_w,
            px_h,
            page_w=opts.page_w,
            page_h=opts.page_h,
            fit=opts.image_fit,
            align=opts.image_align,
            min_dpi=opts.min_dpi,
        )
        warnings.extend(placement.warnings)
        prepared = prepare_image(
            image_path,
            placement,
            to_cmyk=opts.to_cmyk,
            max_dpi=opts.max_dpi,
            jpeg_quality=opts.jpeg_quality,
        )
        warnings.extend(prepared.warnings)
    else:
        warnings.append("no artwork supplied; the PDF holds the cut line only")

    trim = (
        cut.bbox.xmin,
        cut.bbox.ymin,
        cut.bbox.xmax,
        cut.bbox.ymax,
    )
    pdf_opts = PdfOptions(
        page_w_mm=opts.page_w,
        page_h_mm=opts.page_h,
        stroke_pt=opts.stroke_pt,
        spot_name=opts.spot_name,
        spot_cmyk=opts.spot_cmyk,
        overprint=opts.overprint,
        trim_mm=trim,
        title=opts.title,
        layers=opts.pdf_layers,
    )

    try:
        write_pdf(out_path, cut.contours, pdf_opts, prepared, placement)
    finally:
        if prepared is not None:
            imaging.cleanup(prepared)

    report = {
        "dxf_units": dxf.unit_name,
        "dxf_layers": dxf.layers,
        "contours": len(cut.contours),
        "closed_contours": sum(1 for c in cut.contours if c.closed),
        "cut_size_mm": (round(cut.bbox.width, 2), round(cut.bbox.height, 2)),
        "cut_scale": round(cut.scale, 6),
        "bleed_mm": tuple(round(v, 2) for v in cut.bleed_mm),
        "page_mm": (opts.page_w, opts.page_h),
        "spot_name": opts.spot_name,
        "stroke_pt": opts.stroke_pt,
        "overprint": opts.overprint,
        "artwork_dpi": round(placement.effective_dpi, 1) if placement else None,
    }

    return JobResult(out_path, cut.contours, placement, prepared, warnings, report)


def build_preview(result: JobResult, opts: JobOptions, dpi: float = 72.0) -> Image.Image:
    return preview.render_preview(
        result.contours,
        opts.page_w,
        opts.page_h,
        result.prepared_image,
        result.image_placement,
        dpi=dpi,
    )
