import math
import os

import pikepdf
import pytest
from PIL import Image

from kutcontour.cli import main
from kutcontour.core import JobOptions, build_pdf, build_preview
from kutcontour.pdfwriter import MM_TO_PT, describe_pdf


def build(tmp_path, sample_dxf, artwork=None, **kwargs):
    out = str(tmp_path / "out.pdf")
    return build_pdf(sample_dxf, artwork, out, JobOptions(**kwargs)), out


def test_pdf_has_the_spot_colour_overprint_and_page_size(tmp_path, sample_dxf, artwork):
    _result, out = build(tmp_path, sample_dxf, artwork)
    info = describe_pdf(out)
    assert info["page_mm"] == (263.0, 303.0)
    assert info["separations"] == ["CutContour"]
    assert info["overprint"] is True
    assert info["layers"] == ["Artwork", "CutContour"]
    assert b"/CutContour CS" in info["stream"]


def test_separation_alternates_to_100_percent_magenta(tmp_path, sample_dxf):
    _result, out = build(tmp_path, sample_dxf)
    with pikepdf.open(out) as pdf:
        cs = pdf.pages[0].Resources.ColorSpace.CutContour
        assert str(cs[0]) == "/Separation"
        assert str(cs[1]) == "/CutContour"
        assert str(cs[2]) == "/DeviceCMYK"
        assert [float(v) for v in cs[3]["/Range"]] == [0, 1, 0, 1, 0, 1, 0, 1]
        # The tint transform scales magenta by the tint and leaves C, Y and K at zero.
        body = cs[3].read_bytes().decode()
        assert "1.0 mul" in body
        assert body.count("0.0") == 3


def test_stroke_width_and_no_overprint_are_honoured(tmp_path, sample_dxf):
    _result, out = build(tmp_path, sample_dxf, stroke_pt=0.25, overprint=False)
    info = describe_pdf(out)
    assert info["overprint"] is False
    assert b".25 w" in info["stream"]


def test_custom_spot_name(tmp_path, sample_dxf):
    _result, out = build(tmp_path, sample_dxf, spot_name="Thru-cut")
    assert describe_pdf(out)["separations"] == ["Thru-cut"]


def test_trim_box_marks_the_cut_line(tmp_path, sample_dxf, artwork):
    _result, out = build(tmp_path, sample_dxf, artwork)
    with pikepdf.open(out) as pdf:
        trim = [float(v) / MM_TO_PT for v in pdf.pages[0].obj["/TrimBox"]]
        media = [float(v) / MM_TO_PT for v in pdf.pages[0].obj["/MediaBox"]]
    assert math.isclose(trim[0], 1.5, abs_tol=0.01)
    assert math.isclose(trim[2], 261.5, abs_tol=0.01)
    assert math.isclose(media[2], 263.0, abs_tol=0.01)


def test_layers_can_be_switched_off(tmp_path, sample_dxf, artwork):
    _result, out = build(tmp_path, sample_dxf, artwork, pdf_layers=False)
    info = describe_pdf(out)
    assert info["layers"] == []
    assert b"BDC" not in info["stream"]
    assert info["separations"] == ["CutContour"]


def test_report_and_warnings(tmp_path, sample_dxf, artwork):
    result, _out = build(tmp_path, sample_dxf, artwork)
    assert result.report["cut_size_mm"] == (260.0, 300.0)
    assert result.report["bleed_mm"] == (1.5, 1.5)
    assert result.report["closed_contours"] == 2
    assert any("cropped away" in w for w in result.warnings)


def test_cut_line_only_pdf_says_so(tmp_path, sample_dxf):
    result, out = build(tmp_path, sample_dxf)
    assert any("no artwork" in w for w in result.warnings)
    assert os.path.getsize(out) > 0


def test_cmyk_conversion(tmp_path, sample_dxf, artwork):
    result, _out = build(tmp_path, sample_dxf, artwork, to_cmyk=True)
    assert result.prepared_image.image.mode == "CMYK"
    assert any("CMYK" in w for w in result.warnings)


def test_temporary_files_are_cleaned_up(tmp_path, sample_dxf, artwork):
    jpg = tmp_path / "art.jpg"
    Image.open(artwork).convert("RGB").save(jpg, quality=95)
    result, _out = build(tmp_path, sample_dxf, str(jpg))
    assert all(not os.path.exists(p) for p in result.prepared_image.temp_files)


def test_preview_matches_the_page_shape(tmp_path, sample_dxf, artwork):
    opts = JobOptions()
    result = build_pdf(sample_dxf, artwork, str(tmp_path / "o.pdf"), opts)
    img = build_preview(result, opts, dpi=25.4)  # 1 px per mm
    assert img.size == (263, 303)


def test_cli_build_then_verify(tmp_path, sample_dxf, artwork, capsys):
    out = tmp_path / "cli.pdf"
    preview = tmp_path / "cli.png"
    code = main(["build", "--dxf", sample_dxf, "-i", artwork, "-o", str(out),
                 "--preview", str(preview)])
    assert code == 0
    assert out.exists() and preview.exists()
    capsys.readouterr()
    assert main(["verify", str(out)]) == 0
    assert "spot colour CutContour present" in capsys.readouterr().out


def test_cli_verify_fails_without_overprint(tmp_path, sample_dxf, capsys):
    out = tmp_path / "flat.pdf"
    main(["build", "--dxf", sample_dxf, "-o", str(out), "--no-overprint"])
    assert main(["verify", str(out)]) == 1


def test_cli_inspect_and_template(tmp_path, sample_dxf, capsys):
    assert main(["inspect", "--dxf", sample_dxf]) == 0
    assert "260.00 x 300.00 mm" in capsys.readouterr().out
    png = tmp_path / "t.png"
    assert main(["template", "--dxf", sample_dxf, "-o", str(png), "--dpi", "72"]) == 0
    assert Image.open(png).size == (round(263 * 72 / 25.4), round(303 * 72 / 25.4))


def test_cli_reports_a_missing_cut_file(tmp_path):
    with pytest.raises(SystemExit):
        main(["build", "--dxf", str(tmp_path / "nope.dxf")])


def test_cli_rejects_a_bad_page_size(sample_dxf):
    with pytest.raises(SystemExit):
        main(["build", "--dxf", sample_dxf, "--page", "wide"])
