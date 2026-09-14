"""Geometry primitives: contours made of lines and cubic beziers, in millimetres."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

Point = tuple[float, float]

# Commands are ("L", (end,)) or ("C", (ctrl1, ctrl2, end)).
Command = tuple[str, tuple[Point, ...]]


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> Point:
        return ((self.xmin + self.xmax) / 2.0, (self.ymin + self.ymax) / 2.0)

    @staticmethod
    def union(boxes: Iterable["BBox"]) -> "BBox":
        boxes = list(boxes)
        if not boxes:
            raise ValueError("cannot take the bounding box of nothing")
        return BBox(
            min(b.xmin for b in boxes),
            min(b.ymin for b in boxes),
            max(b.xmax for b in boxes),
            max(b.ymax for b in boxes),
        )


def _cubic_extrema(p0: float, p1: float, p2: float, p3: float) -> list[float]:
    """Values of a cubic bezier component at its extrema (plus both endpoints)."""
    values = [p0, p3]
    # B'(t) = 3(a t^2 + b t + c)
    a = -p0 + 3 * p1 - 3 * p2 + p3
    b = 2 * (p0 - 2 * p1 + p2)
    c = -p0 + p1
    roots: list[float] = []
    if abs(a) < 1e-12:
        if abs(b) > 1e-12:
            roots.append(-c / b)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            sq = math.sqrt(disc)
            roots.extend([(-b + sq) / (2 * a), (-b - sq) / (2 * a)])
    for t in roots:
        if 0.0 < t < 1.0:
            mt = 1 - t
            values.append(
                mt**3 * p0 + 3 * mt**2 * t * p1 + 3 * mt * t**2 * p2 + t**3 * p3
            )
    return values


@dataclass
class Contour:
    """A single sub-path: a start point followed by line/curve commands."""

    start: Point
    commands: list[Command] = field(default_factory=list)
    closed: bool = False
    layer: str = ""

    @property
    def end(self) -> Point:
        if not self.commands:
            return self.start
        return self.commands[-1][1][-1]

    def bbox(self) -> BBox:
        xs = [self.start[0]]
        ys = [self.start[1]]
        cur = self.start
        for kind, pts in self.commands:
            if kind == "L":
                xs.append(pts[0][0])
                ys.append(pts[0][1])
            else:
                c1, c2, end = pts
                xs.extend(_cubic_extrema(cur[0], c1[0], c2[0], end[0]))
                ys.extend(_cubic_extrema(cur[1], c1[1], c2[1], end[1]))
            cur = pts[-1]
        return BBox(min(xs), min(ys), max(xs), max(ys))

    def transform(self, fn: Callable[[Point], Point]) -> "Contour":
        return Contour(
            start=fn(self.start),
            commands=[(kind, tuple(fn(p) for p in pts)) for kind, pts in self.commands],
            closed=self.closed,
            layer=self.layer,
        )

    def scaled_translated(self, scale: float, dx: float, dy: float) -> "Contour":
        return self.transform(lambda p: (p[0] * scale + dx, p[1] * scale + dy))

    def reversed_(self) -> "Contour":
        """Reverse direction; only used when stitching open segments together."""
        pts: list[tuple[str, tuple[Point, ...]]] = []
        cur = self.start
        stack: list[tuple[str, Point, tuple[Point, ...]]] = []
        for kind, cmd_pts in self.commands:
            stack.append((kind, cur, cmd_pts))
            cur = cmd_pts[-1]
        new_start = cur
        for kind, seg_start, cmd_pts in reversed(stack):
            if kind == "L":
                pts.append(("L", (seg_start,)))
            else:
                c1, c2, _end = cmd_pts
                pts.append(("C", (c2, c1, seg_start)))
        return Contour(new_start, pts, self.closed, self.layer)

    def length_estimate(self, samples: int = 16) -> float:
        """Rough path length, used to sort/report contours."""
        total = 0.0
        cur = self.start
        for kind, pts in self.commands:
            if kind == "L":
                total += math.dist(cur, pts[0])
            else:
                c1, c2, end = pts
                prev = cur
                for i in range(1, samples + 1):
                    t = i / samples
                    mt = 1 - t
                    pt = (
                        mt**3 * cur[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * end[0],
                        mt**3 * cur[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * end[1],
                    )
                    total += math.dist(prev, pt)
                    prev = pt
            cur = pts[-1]
        if self.closed:
            total += math.dist(cur, self.start)
        return total


def contours_bbox(contours: Sequence[Contour]) -> BBox:
    return BBox.union(c.bbox() for c in contours)


def stitch(contours: Sequence[Contour], tol: float = 0.01) -> list[Contour]:
    """Join contours whose endpoints touch, then close the ones that come full circle.

    DXF cut files are often exported as loose LINE/ARC entities rather than a single
    polyline; this puts them back together so the PDF gets real closed paths.
    """
    closed = [c for c in contours if c.closed]
    open_ = [c for c in contours if not c.closed]

    result: list[Contour] = []
    while open_:
        current = open_.pop(0)
        merged = True
        while merged:
            merged = False
            for i, other in enumerate(open_):
                for cur_flip in (False, True):
                    head = current.reversed_() if cur_flip else current
                    for other_flip in (False, True):
                        tail = other.reversed_() if other_flip else other
                        if math.dist(head.end, tail.start) <= tol:
                            # The gap is <= tol, so simply concatenating is enough.
                            current = Contour(
                                head.start,
                                head.commands + tail.commands,
                                False,
                                head.layer or tail.layer,
                            )
                            open_.pop(i)
                            merged = True
                            break
                    if merged:
                        break
                if merged:
                    break
        if len(current.commands) and math.dist(current.end, current.start) <= tol:
            current.closed = True
        result.append(current)

    return closed + result


def flatten(contour: Contour, samples_per_curve: int = 24) -> list[Point]:
    """Approximate a contour with a polyline. Used for previews, not for output."""
    points: list[Point] = [contour.start]
    cur = contour.start
    for kind, pts in contour.commands:
        if kind == "L":
            points.append(pts[0])
        else:
            c1, c2, end = pts
            for i in range(1, samples_per_curve + 1):
                t = i / samples_per_curve
                mt = 1 - t
                points.append(
                    (
                        mt**3 * cur[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * end[0],
                        mt**3 * cur[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * end[1],
                    )
                )
        cur = pts[-1]
    if contour.closed and points[-1] != points[0]:
        points.append(points[0])
    return points
