"""A small local web interface: drop artwork in, get the print-ready PDF out."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import asdict

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from .core import JobOptions, build_pdf, build_preview
from .geometry import flatten
from .dxfread import DxfError, read_dxf
from .layout import MAX_CUT_HEIGHT_MM, MAX_CUT_WIDTH_MM, PAGE_HEIGHT_MM, PAGE_WIDTH_MM, place_cut
from .pdfwriter import DEFAULT_STROKE_PT, SPOT_NAME
from .preview import render_template as render_design_template

MAX_UPLOAD_BYTES = 128 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}


def cutfile_dir() -> str:
    return os.path.abspath(os.environ.get("KUTCONTOUR_CUTFILES", "cutfiles"))


def list_cutfiles() -> list[str]:
    directory = cutfile_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(f for f in os.listdir(directory) if f.lower().endswith(".dxf"))


def resolve_cutfile(name: str) -> str:
    """Map a posted cut-file name onto a real file, refusing anything outside the folder."""
    safe = secure_filename(name or "")
    path = os.path.join(cutfile_dir(), safe)
    if not safe or not os.path.isfile(path):
        abort(400, f"unknown cut file: {name}")
    return path


def _float(name: str, default: float) -> float:
    raw = request.form.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        abort(400, f"{name} must be a number")


def create_app(output_dir: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    outputs = output_dir or os.path.join(tempfile.gettempdir(), "kutcontour-output")
    os.makedirs(outputs, exist_ok=True)
    app.config["KUTCONTOUR_OUTPUT"] = outputs

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            cutfiles=list_cutfiles(),
            defaults={
                "page_w": PAGE_WIDTH_MM,
                "page_h": PAGE_HEIGHT_MM,
                "max_cut_w": MAX_CUT_WIDTH_MM,
                "max_cut_h": MAX_CUT_HEIGHT_MM,
                "stroke": DEFAULT_STROKE_PT,
                "spot_name": SPOT_NAME,
            },
        )

    @app.get("/api/cutfiles")
    def api_cutfiles():
        result = []
        for name in list_cutfiles():
            try:
                res = read_dxf(os.path.join(cutfile_dir(), name))
                placed = place_cut(res.contours)
                result.append(
                    {
                        "name": name,
                        "paths": len(res.contours),
                        "width_mm": round(placed.bbox.width, 2),
                        "height_mm": round(placed.bbox.height, 2),
                        "warnings": res.warnings + placed.warnings,
                    }
                )
            except DxfError as exc:
                result.append({"name": name, "error": str(exc)})
        return jsonify(result)

    @app.post("/api/cutline")
    def api_cutline():
        """The cut line as polylines in mm, so the browser can draw it live."""
        upload = request.files.get("dxf")
        if upload and upload.filename:
            workdir = os.path.join(outputs, "cutline-" + uuid.uuid4().hex)
            os.makedirs(workdir, exist_ok=True)
            dxf_path = os.path.join(workdir, "cut.dxf")
            upload.save(dxf_path)
        else:
            dxf_path = resolve_cutfile(request.form.get("cutfile", ""))

        page_w = _float("page_w", PAGE_WIDTH_MM)
        page_h = _float("page_h", PAGE_HEIGHT_MM)
        try:
            res = read_dxf(dxf_path, units=request.form.get("units") or None)
        except DxfError as exc:
            abort(400, str(exc))
        placed = place_cut(res.contours, page_w=page_w, page_h=page_h)
        return jsonify(
            {
                "page_mm": [page_w, page_h],
                "cut_mm": [round(placed.bbox.width, 2), round(placed.bbox.height, 2)],
                "paths": [
                    [[round(x, 2), round(y, 2)] for x, y in flatten(c, samples_per_curve=12)]
                    for c in placed.contours
                ],
                "warnings": res.warnings + placed.warnings,
            }
        )

    @app.post("/api/generate")
    def api_generate():
        job_id = uuid.uuid4().hex
        workdir = os.path.join(outputs, job_id)
        os.makedirs(workdir, exist_ok=True)

        upload = request.files.get("image")
        image_path = None
        if upload and upload.filename:
            ext = os.path.splitext(upload.filename)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                abort(400, f"unsupported artwork type {ext or '(none)'}")
            image_path = os.path.join(workdir, "artwork" + ext)
            upload.save(image_path)

        dxf_upload = request.files.get("dxf")
        if dxf_upload and dxf_upload.filename:
            dxf_path = os.path.join(workdir, "cut.dxf")
            dxf_upload.save(dxf_path)
        else:
            dxf_path = resolve_cutfile(request.form.get("cutfile", ""))

        opts = JobOptions(
            page_w=_float("page_w", PAGE_WIDTH_MM),
            page_h=_float("page_h", PAGE_HEIGHT_MM),
            max_cut_w=_float("max_cut_w", MAX_CUT_WIDTH_MM),
            max_cut_h=_float("max_cut_h", MAX_CUT_HEIGHT_MM),
            units=request.form.get("units") or None,
            image_fit=request.form.get("image_fit", "cover"),
            image_align=request.form.get("image_align", "center"),
            image_scale=_float("image_scale", 1.0),
            image_offset_x=_float("image_offset_x", 0.0),
            image_offset_y=_float("image_offset_y", 0.0),
            to_cmyk=request.form.get("cmyk") == "on",
            fit_cut=request.form.get("fit_cut") == "on",
            overprint=request.form.get("overprint", "on") == "on",
            stroke_pt=_float("stroke", DEFAULT_STROKE_PT),
            spot_name=request.form.get("spot_name") or SPOT_NAME,
        )

        name = os.path.splitext(secure_filename(upload.filename))[0] if upload and upload.filename else "cutfile"
        pdf_name = f"{name or 'cutfile'}-cutcontour.pdf"
        pdf_path = os.path.join(workdir, pdf_name)

        try:
            result = build_pdf(dxf_path, image_path, pdf_path, opts)
        except (DxfError, ValueError) as exc:
            abort(400, str(exc))

        preview_path = os.path.join(workdir, "preview.png")
        build_preview(result, opts, dpi=96).save(preview_path)

        return jsonify(
            {
                "id": job_id,
                "pdf_url": f"/download/{job_id}/{pdf_name}",
                "preview_url": f"/preview/{job_id}",
                "report": result.report,
                "warnings": result.warnings,
            }
        )

    @app.get("/preview/<job_id>")
    def preview(job_id: str):
        path = os.path.join(outputs, secure_filename(job_id), "preview.png")
        if not os.path.isfile(path):
            abort(404)
        return send_file(path, mimetype="image/png")

    @app.get("/download/<job_id>/<filename>")
    def download(job_id: str, filename: str):
        path = os.path.join(outputs, secure_filename(job_id), secure_filename(filename))
        if not os.path.isfile(path):
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=filename)

    @app.get("/template/<cutfile>")
    def template_png(cutfile: str):
        path = resolve_cutfile(cutfile)
        res = read_dxf(path)
        placed = place_cut(res.contours)
        img = render_design_template(placed.contours, PAGE_WIDTH_MM, PAGE_HEIGHT_MM, dpi=150)
        out = os.path.join(outputs, f"template-{secure_filename(cutfile)}.png")
        img.save(out, dpi=(150, 150))
        return send_file(out, mimetype="image/png", as_attachment=True,
                         download_name=os.path.splitext(cutfile)[0] + "-template.png")

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
