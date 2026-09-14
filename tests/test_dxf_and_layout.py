import math

import pytest

from kutcontour.dxfread import DxfError, read_dxf
from kutcontour.geometry import contours_bbox
from kutcontour.layout import place_cut, place_image


def test_reads_sample_as_two_closed_paths_at_the_right_size(sample_dxf):
    res = read_dxf(sample_dxf)
    assert len(res.contours) == 2
    assert all(c.closed for c in res.contours)
    box = contours_bbox(res.contours)
    assert math.isclose(box.width, 260.0, abs_tol=0.01)
    assert math.isclose(box.height, 300.0, abs_tol=0.01)
    assert res.warnings == []


def test_unit_override_rescales(sample_dxf):
    res = read_dxf(sample_dxf, units="cm")
    assert math.isclose(contours_bbox(res.contours).width, 2600.0, abs_tol=0.1)


def test_unknown_unit_is_rejected(sample_dxf):
    with pytest.raises(DxfError):
        read_dxf(sample_dxf, units="furlong")


def test_layer_filter_can_exclude_everything(sample_dxf):
    with pytest.raises(DxfError):
        read_dxf(sample_dxf, layers=["nope"])
    assert len(read_dxf(sample_dxf, layers=["CutContour"]).contours) == 2


def test_missing_file(tmp_path):
    with pytest.raises(DxfError):
        read_dxf(str(tmp_path / "absent.dxf"))


def test_place_cut_centres_with_even_bleed(sample_dxf):
    placed = place_cut(read_dxf(sample_dxf).contours)
    assert math.isclose(placed.bbox.xmin, 1.5, abs_tol=0.01)
    assert math.isclose(placed.bbox.ymin, 1.5, abs_tol=0.01)
    assert math.isclose(placed.bleed_mm[0], 1.5, abs_tol=0.01)
    assert placed.scale == 1.0
    assert placed.warnings == []


def test_oversized_cut_warns_but_is_not_silently_resized(sample_dxf):
    contours = [c.scaled_translated(1.2, 0, 0) for c in read_dxf(sample_dxf).contours]
    placed = place_cut(contours)
    assert placed.scale == 1.0
    assert any("larger than" in w for w in placed.warnings)


def test_fit_scales_an_oversized_cut_down(sample_dxf):
    contours = [c.scaled_translated(1.2, 0, 0) for c in read_dxf(sample_dxf).contours]
    placed = place_cut(contours, fit=True)
    assert math.isclose(placed.bbox.width, 260.0, abs_tol=0.01)
    assert any("scaled by" in w for w in placed.warnings)


def test_cover_crops_a_landscape_image_to_the_portrait_page():
    p = place_image(3000, 2000, fit="cover")
    assert (p.width_mm, p.height_mm) == (263.0, 303.0)
    left, top, right, bottom = p.crop_px
    assert math.isclose((right - left) / (bottom - top), 263.0 / 303.0, rel_tol=1e-3)
    assert left > 0 and top == 0  # cropped horizontally, centred
    assert any("cropped away" in w for w in p.warnings)


def test_cover_alignment_picks_which_edge_to_keep():
    assert place_image(3000, 2000, fit="cover", align="left").crop_px[0] == 0
    right = place_image(3000, 2000, fit="cover", align="right")
    assert right.crop_px[2] == 3000


def test_contain_letterboxes_and_warns():
    p = place_image(3000, 2000, fit="contain")
    assert p.crop_px is None
    assert math.isclose(p.width_mm, 263.0, abs_tol=0.01)
    assert p.height_mm < 303.0
    assert any("white" in w for w in p.warnings)


def test_stretch_fills_the_page_exactly():
    p = place_image(3000, 2000, fit="stretch")
    assert (p.width_mm, p.height_mm) == (263.0, 303.0)
    assert p.crop_px is None


def test_low_resolution_artwork_warns():
    p = place_image(600, 700, fit="stretch")
    assert p.effective_dpi < 150
    assert any("dpi" in w for w in p.warnings)


def test_unknown_fit_mode():
    with pytest.raises(ValueError):
        place_image(100, 100, fit="squish")
