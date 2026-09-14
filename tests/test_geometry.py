import math

from kutcontour.geometry import BBox, Contour, flatten, stitch


def test_cubic_bbox_uses_real_extrema_not_control_points():
    # Control points reach y=3 but the curve itself peaks at y=2.25.
    curve = Contour((0.0, 0.0), [("C", ((0.0, 3.0), (1.0, 3.0), (1.0, 0.0)))])
    box = curve.bbox()
    assert math.isclose(box.ymax, 2.25, abs_tol=1e-9)
    assert math.isclose(box.ymin, 0.0, abs_tol=1e-9)


def test_bbox_union():
    box = BBox.union([BBox(0, 0, 1, 1), BBox(-2, 3, 0, 4)])
    assert (box.xmin, box.ymin, box.xmax, box.ymax) == (-2, 0, 1, 4)


def test_scaled_translated():
    c = Contour((1.0, 2.0), [("L", ((3.0, 4.0),))])
    moved = c.scaled_translated(2.0, 10.0, 20.0)
    assert moved.start == (12.0, 24.0)
    assert moved.commands[0][1][0] == (16.0, 28.0)


def test_reverse_keeps_geometry():
    c = Contour((0.0, 0.0), [("L", ((1.0, 0.0),)), ("C", ((2.0, 1.0), (3.0, 1.0), (4.0, 0.0)))])
    r = c.reversed_()
    assert r.start == (4.0, 0.0)
    assert r.end == (0.0, 0.0)
    assert math.isclose(r.length_estimate(), c.length_estimate(), rel_tol=1e-9)


def test_stitch_joins_loose_segments_into_a_closed_square():
    segments = [
        Contour((0.0, 0.0), [("L", ((10.0, 0.0),))]),
        Contour((10.0, 10.0), [("L", ((0.0, 10.0),))]),
        Contour((10.0, 0.0), [("L", ((10.0, 10.0),))]),
        Contour((0.0, 10.0), [("L", ((0.0, 0.0),))]),
    ]
    result = stitch(segments)
    assert len(result) == 1
    assert result[0].closed
    assert math.isclose(result[0].length_estimate(), 40.0, rel_tol=1e-9)


def test_stitch_flips_segments_that_run_the_other_way():
    segments = [
        Contour((0.0, 0.0), [("L", ((10.0, 0.0),))]),
        Contour((10.0, 5.0), [("L", ((10.0, 0.0),))]),  # reversed
    ]
    result = stitch(segments)
    assert len(result) == 1
    assert not result[0].closed
    assert math.isclose(result[0].length_estimate(), 15.0, rel_tol=1e-9)


def test_stitch_leaves_far_apart_segments_alone():
    segments = [
        Contour((0.0, 0.0), [("L", ((1.0, 0.0),))]),
        Contour((50.0, 0.0), [("L", ((51.0, 0.0),))]),
    ]
    assert len(stitch(segments, tol=0.05)) == 2


def test_flatten_closes_the_loop():
    c = Contour((0.0, 0.0), [("L", ((1.0, 0.0),)), ("L", ((1.0, 1.0),))], closed=True)
    points = flatten(c)
    assert points[0] == points[-1] == (0.0, 0.0)
