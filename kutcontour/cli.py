"""Command line interface."""

from __future__ import annotations

import argparse
import glob
import os
import sys

from .core import JobOptions, build_pdf, build_preview
from .dxfread import DxfError, read_dxf
from .geometry import contours_bbox
from .layout import (
    MAX_CUT_HEIGHT_MM,
    MAX_CUT_WIDTH_MM,
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    place_cut,
)
from .pdfwriter import DEFAULT_STROKE_PT, SPOT_NAME, describe_pdf
from .preview import render_template

CUTFILE_DIR = os.environ.get("KUTCONTOUR_CUTFILES", "cutfiles")


def default_dxf() -> str | None:
    """The usual case is one reusable cut file, so find it without being told."""
    env = os.environ.get("KUTCONTOUR_DXF")
    if env:
        return env
    candidates = sorted(glob.glob(os.path.join(CUTFILE_DIR, "*.dxf")))
    if len(candidates) == 1:
        return candidates[0]
    return None


def _parse_cmyk(text: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("expected four comma-separated values, e.g. 0,100,0,0")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if any(v < 0 or v > 100 for v in values):
        raise argparse.ArgumentTypeError("CMYK values run from 0 to 100")
    return tuple(v / 100.0 for v in values)  # type: ignore[return-value]


def _add_shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dxf", help="cut file (default: the single .dxf in ./cutfiles)")
    p.add_argument("--page", default=f"{PAGE_WIDTH_MM}x{PAGE_HEIGHT_MM}", help="page size in mm, WxH")
    p.add_argument(
        "--max-cut",
        default=f"{MAX_CUT_WIDTH_MM}x{MAX_CUT_HEIGHT_MM}",
        help="largest allowed cut size in mm, WxH",
    )
    p.add_argument("--units", choices=["mm", "cm", "m", "in", "ft"], help="override the DXF's own units")
    p.add_argument("--layer", action="append", dest="layers", help="only read this DXF layer (repeatable)")


def _parse_size(text: str, what: str) -> tuple[float, float]:
    try:
        w, h = text.lower().split("x")
        return float(w), float(h)
    except ValueError:
        raise SystemExit(f"{what} must look like 263x303")


def _options(args) -> JobOptions:
    page_w, page_h = _parse_size(args.page, "--page")
    max_w, max_h = _parse_size(args.max_cut, "--max-cut")
    opts = JobOptions(
        page_w=page_w,
        page_h=page_h,
        max_cut_w=max_w,
        max_cut_h=max_h,
        units=args.units,
        layers=args.layers,
    )
    for name in (
        "center", "fit_cut", "image_fit", "image_align", "to_cmyk", "max_dpi",
        "min_dpi", "stroke_pt", "spot_name", "spot_cmyk", "overprint", "pdf_layers",
    ):
        if hasattr(args, name) and getattr(args, name) is not None:
            setattr(opts, name, getattr(args, name))
    return opts


def _resolve_dxf(args) -> str:
    path = args.dxf or default_dxf()
    if not path:
        found = sorted(glob.glob(os.path.join(CUTFILE_DIR, "*.dxf")))
        if len(found) > 1:
            raise SystemExit(
                "several cut files in " + CUTFILE_DIR + "; pick one with --dxf:\n  "
                + "\n  ".join(found)
            )
        raise SystemExit(
            "no cut file given: pass --dxf, set KUTCONTOUR_DXF, or put one .dxf in ./cutfiles"
        )
    if not os.path.isfile(path):
        raise SystemExit(f"cut file not found: {path}")
    return path


def cmd_build(args) -> int:
    dxf = _resolve_dxf(args)
    if args.image and not os.path.isfile(args.image):
        raise SystemExit(f"artwork not found: {args.image}")
    opts = _options(args)
    result = build_pdf(dxf, args.image, args.out, opts)

    print(f"wrote {result.pdf_path}")
    r = result.report
    print(f"  page        {r['page_mm'][0]:g} x {r['page_mm'][1]:g} mm")
    print(f"  cut line    {r['cut_size_mm'][0]:g} x {r['cut_size_mm'][1]:g} mm"
          f" ({r['contours']} paths, {r['closed_contours']} closed)")
    print(f"  bleed       {r['bleed_mm'][0]:g} / {r['bleed_mm'][1]:g} mm")
    print(f"  spot colour {r['spot_name']}, {r['stroke_pt']:g} pt"
          f"{', overprint' if r['overprint'] else ', NO overprint'}")
    if r["artwork_dpi"]:
        print(f"  artwork     {r['artwork_dpi']:g} dpi at final size")
    for w in result.warnings:
        print(f"  ! {w}", file=sys.stderr)

    if args.preview:
        build_preview(result, opts, dpi=args.preview_dpi).save(args.preview)
        print(f"wrote {args.preview}")
    return 0


def cmd_inspect(args) -> int:
    dxf = _resolve_dxf(args)
    res = read_dxf(dxf, units=args.units, layers=args.layers)
    box = contours_bbox(res.contours)
    page_w, page_h = _parse_size(args.page, "--page")
    max_w, max_h = _parse_size(args.max_cut, "--max-cut")
    placed = place_cut(res.contours, page_w, page_h, max_w, max_h)

    print(f"{dxf}")
    print(f"  units       {res.unit_name} (x{res.scale_to_mm:g} to mm)")
    print(f"  layers      {', '.join(res.layers)}")
    print(f"  paths       {len(res.contours)} ({sum(1 for c in res.contours if c.closed)} closed)")
    print(f"  size        {box.width:.2f} x {box.height:.2f} mm")
    print(f"  on page     bleed {placed.bleed_mm[0]:.2f} / {placed.bleed_mm[1]:.2f} mm")
    for i, c in enumerate(sorted(res.contours, key=lambda c: -c.length_estimate()), 1):
        b = c.bbox()
        print(f"    path {i}: {b.width:.2f} x {b.height:.2f} mm, "
              f"{c.length_estimate():.1f} mm long, {'closed' if c.closed else 'OPEN'}")
    for w in res.warnings + placed.warnings:
        print(f"  ! {w}", file=sys.stderr)
    return 0


def cmd_template(args) -> int:
    dxf = _resolve_dxf(args)
    page_w, page_h = _parse_size(args.page, "--page")
    max_w, max_h = _parse_size(args.max_cut, "--max-cut")
    res = read_dxf(dxf, units=args.units, layers=args.layers)
    placed = place_cut(res.contours, page_w, page_h, max_w, max_h)
    img = render_template(placed.contours, page_w, page_h, dpi=args.dpi, safe_margin_mm=args.safe_margin)
    img.save(args.out, dpi=(args.dpi, args.dpi))
    print(f"wrote {args.out} ({img.width} x {img.height} px at {args.dpi:g} dpi)")
    print(f"  design at {page_w:g} x {page_h:g} mm and let the background run to the edge")
    return 0


def cmd_verify(args) -> int:
    info = describe_pdf(args.pdf)
    ok = True
    print(args.pdf)
    print(f"  page        {info['page_mm'][0]:g} x {info['page_mm'][1]:g} mm")
    if args.spot_name in info["separations"]:
        print(f"  spot colour {args.spot_name} present")
    else:
        print(f"  spot colour MISSING (found: {info['separations'] or 'none'})")
        ok = False
    print(f"  overprint   {'on' if info['overprint'] else 'OFF'}")
    ok = ok and info["overprint"]
    print(f"  layers      {', '.join(info['layers']) or 'none'}")
    return 0 if ok else 1


def cmd_serve(args) -> int:
    from .webapp import create_app

    app = create_app()
    print(f"KutContour is running on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kutcontour",
        description="Turn a reusable DXF cut file plus artwork into a print-ready "
                    "PDF with a CutContour spot-colour cut line.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="make the print-ready PDF")
    _add_shared(b)
    b.add_argument("-i", "--image", help="artwork to place under the cut line")
    b.add_argument("-o", "--out", default="output.pdf", help="output PDF (default: output.pdf)")
    b.add_argument("--image-fit", choices=["cover", "contain", "stretch"], default="cover",
                   dest="image_fit", help="how artwork fills the page (default: cover)")
    b.add_argument("--image-align", choices=["center", "top", "bottom", "left", "right"],
                   default="center", dest="image_align", help="which part to keep when cropping")
    b.add_argument("--fit", action="store_true", dest="fit_cut",
                   help="scale the cut line down if it exceeds the maximum size")
    b.add_argument("--no-center", action="store_false", dest="center",
                   help="keep the DXF's own coordinates instead of centring")
    b.add_argument("--cmyk", action="store_true", dest="to_cmyk",
                   help="convert artwork to CMYK (no ICC profile; check with your printer)")
    b.add_argument("--stroke", type=float, default=DEFAULT_STROKE_PT, dest="stroke_pt",
                   help=f"cut line width in pt (default: {DEFAULT_STROKE_PT:g})")
    b.add_argument("--spot-name", default=SPOT_NAME, dest="spot_name",
                   help=f"spot colour name (default: {SPOT_NAME})")
    b.add_argument("--spot-cmyk", type=_parse_cmyk, default=None, dest="spot_cmyk",
                   help="spot colour build in percent (default: 0,100,0,0)")
    b.add_argument("--no-overprint", action="store_false", dest="overprint",
                   help="leave overprint off (most printers want it on)")
    b.add_argument("--no-pdf-layers", action="store_false", dest="pdf_layers",
                   help="do not write PDF layers for the artwork and cut line")
    b.add_argument("--max-dpi", type=float, default=600.0, dest="max_dpi",
                   help="downsample artwork above this resolution (default: 600)")
    b.add_argument("--min-dpi", type=float, default=150.0, dest="min_dpi",
                   help="warn below this resolution (default: 150)")
    b.add_argument("--preview", help="also write a PNG preview here")
    b.add_argument("--preview-dpi", type=float, default=96.0, help="preview resolution")
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("inspect", help="report what is in a cut file")
    _add_shared(i)
    i.set_defaults(func=cmd_inspect)

    t = sub.add_parser("template", help="export a PNG to design artwork against")
    _add_shared(t)
    t.add_argument("-o", "--out", default="template.png", help="output PNG (default: template.png)")
    t.add_argument("--dpi", type=float, default=150.0, help="template resolution (default: 150)")
    t.add_argument("--safe-margin", type=float, default=5.0,
                   help="dashed safe-area inset in mm (default: 5)")
    t.set_defaults(func=cmd_template)

    v = sub.add_parser("verify", help="check a finished PDF for the spot colour and overprint")
    v.add_argument("pdf")
    v.add_argument("--spot-name", default=SPOT_NAME)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("serve", help="run the drag-and-drop web interface")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DxfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # Someone piped us into `head`; stop quietly instead of on a traceback.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
