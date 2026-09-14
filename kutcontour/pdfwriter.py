"""Write the print-ready PDF: artwork plus a CutContour spot-colour cut line."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pikepdf
from reportlab.lib.colors import CMYKColorSep
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from .geometry import Contour
from .imaging import PreparedImage
from .layout import ImagePlacement

MM_TO_PT = 72.0 / 25.4

#: What the cutter expects: a spot colour called CutContour, 100% magenta.
SPOT_NAME = "CutContour"
SPOT_CMYK = (0.0, 1.0, 0.0, 0.0)
DEFAULT_STROKE_PT = 1.0

ARTWORK_LAYER = "Artwork"
_OC_ART = "OCArtwork"
_OC_CUT = "OCCutContour"


@dataclass
class PdfOptions:
    page_w_mm: float
    page_h_mm: float
    stroke_pt: float = DEFAULT_STROKE_PT
    spot_name: str = SPOT_NAME
    spot_cmyk: tuple[float, float, float, float] = SPOT_CMYK
    overprint: bool = True
    trim_mm: tuple[float, float, float, float] | None = None
    title: str = "KutContour cut file"
    layers: bool = True


@dataclass
class PdfResult:
    path: str
    warnings: list[str] = field(default_factory=list)


def _draw_contours(c: rl_canvas.Canvas, contours: Sequence[Contour], opts: PdfOptions) -> None:
    spot = CMYKColorSep(*opts.spot_cmyk, spotName=opts.spot_name)
    c.saveState()
    c.setStrokeColor(spot)
    c.setLineWidth(opts.stroke_pt)
    c.setLineJoin(1)  # round joins survive scaling better than mitres
    c.setLineCap(1)
    if opts.overprint:
        c.setStrokeOverprint(True)
    for contour in contours:
        path = c.beginPath()
        path.moveTo(contour.start[0] * MM_TO_PT, contour.start[1] * MM_TO_PT)
        for kind, pts in contour.commands:
            if kind == "L":
                path.lineTo(pts[0][0] * MM_TO_PT, pts[0][1] * MM_TO_PT)
            else:
                (c1, c2, end) = pts
                path.curveTo(
                    c1[0] * MM_TO_PT, c1[1] * MM_TO_PT,
                    c2[0] * MM_TO_PT, c2[1] * MM_TO_PT,
                    end[0] * MM_TO_PT, end[1] * MM_TO_PT,
                )
        if contour.closed:
            path.close()
        c.drawPath(path, stroke=1, fill=0)
    c.restoreState()


def write_pdf(
    out_path: str,
    contours: Sequence[Contour],
    opts: PdfOptions,
    image: PreparedImage | None = None,
    image_placement: ImagePlacement | None = None,
) -> PdfResult:
    """Render `contours` (already positioned, in mm) over `image` into a PDF."""
    page = (opts.page_w_mm * MM_TO_PT, opts.page_h_mm * MM_TO_PT)
    c = rl_canvas.Canvas(out_path, pagesize=page, pageCompression=1)
    c.setTitle(opts.title)
    c.setCreator("KutContour")

    if image is not None and image_placement is not None:
        if opts.layers:
            c.addLiteral(f"/OC /{_OC_ART} BDC")
        source = image.jpeg_path or ImageReader(image.image)
        c.drawImage(
            source,
            image_placement.x_mm * MM_TO_PT,
            image_placement.y_mm * MM_TO_PT,
            image_placement.width_mm * MM_TO_PT,
            image_placement.height_mm * MM_TO_PT,
            preserveAspectRatio=False,
            anchor="sw",
            mask=None,
        )
        if opts.layers:
            c.addLiteral("EMC")

    if opts.layers:
        c.addLiteral(f"/OC /{_OC_CUT} BDC")
    _draw_contours(c, contours, opts)
    if opts.layers:
        c.addLiteral("EMC")

    c.showPage()
    c.save()

    _postprocess(out_path, opts)
    return PdfResult(out_path)


def _postprocess(path: str, opts: PdfOptions) -> None:
    """Add the optional-content groups (so the cut line is a real layer) and boxes."""
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]

        if opts.layers:
            art_ocg = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name.OCG, Name=ARTWORK_LAYER)
            )
            cut_ocg = pdf.make_indirect(
                pikepdf.Dictionary(Type=pikepdf.Name.OCG, Name=opts.spot_name)
            )
            resources = page.obj.get("/Resources")
            if resources is None:
                resources = pikepdf.Dictionary()
                page.obj["/Resources"] = resources
            resources["/Properties"] = pikepdf.Dictionary(
                **{_OC_ART: art_ocg, _OC_CUT: cut_ocg}
            )
            ocgs = pikepdf.Array([art_ocg, cut_ocg])
            pdf.Root["/OCProperties"] = pikepdf.Dictionary(
                OCGs=ocgs,
                D=pikepdf.Dictionary(Order=pikepdf.Array([art_ocg, cut_ocg]), ON=ocgs),
            )

        media = page.obj["/MediaBox"]
        page.obj["/BleedBox"] = pikepdf.Array(list(media))
        if opts.trim_mm:
            x0, y0, x1, y1 = (v * MM_TO_PT for v in opts.trim_mm)
            page.obj["/TrimBox"] = pikepdf.Array([x0, y0, x1, y1])
        else:
            page.obj["/TrimBox"] = pikepdf.Array(list(media))

        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["dc:title"] = opts.title
            meta["pdf:Producer"] = "KutContour"

        pdf.save(path, linearize=False)


def describe_pdf(path: str) -> dict:
    """Read back the things a print shop checks. Used by the verify command and tests."""
    info: dict = {"separations": [], "overprint": False, "layers": [], "page_mm": None}
    with pikepdf.open(path) as pdf:
        page = pdf.pages[0]
        media = [float(v) for v in page.obj["/MediaBox"]]
        info["page_mm"] = (
            round((media[2] - media[0]) / MM_TO_PT, 3),
            round((media[3] - media[1]) / MM_TO_PT, 3),
        )
        resources = page.obj.get("/Resources", pikepdf.Dictionary())
        for _name, cs in dict(resources.get("/ColorSpace", pikepdf.Dictionary())).items():
            if isinstance(cs, pikepdf.Array) and len(cs) >= 3 and str(cs[0]) == "/Separation":
                info["separations"].append(str(cs[1]).lstrip("/"))
        for _name, gs in dict(resources.get("/ExtGState", pikepdf.Dictionary())).items():
            if bool(gs.get("/OP", False)) or bool(gs.get("/op", False)):
                info["overprint"] = True
        ocprops = pdf.Root.get("/OCProperties")
        if ocprops is not None:
            info["layers"] = [str(ocg.get("/Name", "")) for ocg in ocprops.get("/OCGs", [])]
        info["stream"] = bytes(page.Contents.read_bytes())
    return info
