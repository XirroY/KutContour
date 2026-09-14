"""Read cut contours out of a DXF file and hand them back in millimetres."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import ezdxf
from ezdxf import units as ezunits
from ezdxf.path import Command, make_path

from .geometry import Contour, stitch

# DXF $INSUNITS values we know how to convert to mm.
UNIT_NAMES: dict[str, int] = {
    "mm": ezunits.MM,
    "cm": ezunits.CM,
    "m": ezunits.M,
    "in": ezunits.IN,
    "ft": ezunits.FT,
}

#: Entities we can turn into a path. Anything else is ignored (with a warning).
SUPPORTED = {
    "LINE",
    "ARC",
    "CIRCLE",
    "ELLIPSE",
    "LWPOLYLINE",
    "POLYLINE",
    "SPLINE",
    "SOLID",
    "TRACE",
    "3DFACE",
}


class DxfError(RuntimeError):
    pass


@dataclass
class DxfResult:
    contours: list[Contour]
    unit_name: str
    scale_to_mm: float
    layers: list[str]
    warnings: list[str]


def _flatten_entities(entities: Iterable, depth: int = 0) -> Iterable:
    """Expand INSERT (block) references into their component entities."""
    for e in entities:
        if e.dxftype() == "INSERT" and depth < 8:
            yield from _flatten_entities(e.virtual_entities(), depth + 1)
        else:
            yield e


def _path_to_contour(path, layer: str, scale: float) -> Contour | None:
    start = (path.start.x * scale, path.start.y * scale)
    commands: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    cur = start
    for cmd in path.commands():
        if cmd.type == Command.LINE_TO:
            end = (cmd.end.x * scale, cmd.end.y * scale)
            commands.append(("L", (end,)))
            cur = end
        elif cmd.type == Command.CURVE4_TO:
            commands.append(
                (
                    "C",
                    (
                        (cmd.ctrl1.x * scale, cmd.ctrl1.y * scale),
                        (cmd.ctrl2.x * scale, cmd.ctrl2.y * scale),
                        (cmd.end.x * scale, cmd.end.y * scale),
                    ),
                )
            )
            cur = commands[-1][1][-1]
        elif cmd.type == Command.CURVE3_TO:
            # Quadratic -> cubic: control points sit two thirds of the way out.
            ctrl = (cmd.ctrl.x * scale, cmd.ctrl.y * scale)
            end = (cmd.end.x * scale, cmd.end.y * scale)
            c1 = (cur[0] + 2 / 3 * (ctrl[0] - cur[0]), cur[1] + 2 / 3 * (ctrl[1] - cur[1]))
            c2 = (end[0] + 2 / 3 * (ctrl[0] - end[0]), end[1] + 2 / 3 * (ctrl[1] - end[1]))
            commands.append(("C", (c1, c2, end)))
            cur = end
        elif cmd.type == Command.MOVE_TO:
            # A multi-path Path; sub-paths are split by the caller instead.
            return None
    if not commands:
        return None
    return Contour(start=start, commands=commands, closed=bool(path.is_closed), layer=layer)


def read_dxf(
    path: str,
    units: str | None = None,
    layers: Sequence[str] | None = None,
    stitch_tolerance: float = 0.05,
) -> DxfResult:
    """Load `path` and return every contour it holds, scaled to millimetres.

    `units` overrides the file's own $INSUNITS header (handy for the many DXFs
    that are saved as "unitless").
    """
    try:
        doc = ezdxf.readfile(path)
    except IOError as exc:
        raise DxfError(f"cannot read DXF file: {exc}") from exc
    except ezdxf.DXFStructureError as exc:
        raise DxfError(f"not a valid DXF file: {exc}") from exc

    warnings: list[str] = []

    if units:
        key = units.lower()
        if key not in UNIT_NAMES:
            raise DxfError(f"unknown unit {units!r}, pick one of {', '.join(UNIT_NAMES)}")
        src_units = UNIT_NAMES[key]
        unit_name = key
    else:
        src_units = doc.units
        if src_units == 0:
            warnings.append("DXF has no unit set ($INSUNITS = 0); assuming millimetres")
            src_units = ezunits.MM
        unit_name = ezunits.decode(src_units) if hasattr(ezunits, "decode") else str(src_units)

    scale = ezunits.conversion_factor(src_units, ezunits.MM)

    wanted = {layer.lower() for layer in layers} if layers else None
    msp = doc.modelspace()
    seen_layers: set[str] = set()
    contours: list[Contour] = []
    skipped: set[str] = set()

    for entity in _flatten_entities(msp):
        dxftype = entity.dxftype()
        layer = getattr(entity.dxf, "layer", "0")
        seen_layers.add(layer)
        if wanted is not None and layer.lower() not in wanted:
            continue
        if dxftype not in SUPPORTED:
            skipped.add(dxftype)
            continue
        try:
            p = make_path(entity)
        except Exception as exc:  # ezdxf raises a grab-bag of errors here
            skipped.add(dxftype)
            warnings.append(f"skipped {dxftype} on layer {layer!r}: {exc}")
            continue
        contour = _path_to_contour(p, layer, scale)
        if contour is not None:
            contours.append(contour)

    if skipped:
        warnings.append(f"ignored unsupported entities: {', '.join(sorted(skipped))}")
    if not contours:
        raise DxfError("no usable geometry found in the DXF file")

    contours = stitch(contours, tol=stitch_tolerance)
    open_count = sum(1 for c in contours if not c.closed)
    if open_count:
        warnings.append(
            f"{open_count} contour(s) are not closed; a cutter usually wants closed paths"
        )

    return DxfResult(
        contours=contours,
        unit_name=str(unit_name),
        scale_to_mm=scale,
        layers=sorted(seen_layers),
        warnings=warnings,
    )
