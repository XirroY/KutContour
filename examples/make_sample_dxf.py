"""Generate a sample two-path cut file, so the tool can be tried without a real DXF.

Outer path: 260 x 300 mm rounded rectangle. Inner path: a 12 mm hanging hole.
"""

import sys

import ezdxf

W, H, R = 260.0, 300.0, 20.0


def build(path: str) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    cut = doc.layers.add("CutContour")
    cut.color = 6  # magenta

    attribs = {"layer": "CutContour"}
    msp.add_line((R, 0), (W - R, 0), dxfattribs=attribs)
    msp.add_arc((W - R, R), R, 270, 360, dxfattribs=attribs)
    msp.add_line((W, R), (W, H - R), dxfattribs=attribs)
    msp.add_arc((W - R, H - R), R, 0, 90, dxfattribs=attribs)
    msp.add_line((W - R, H), (R, H), dxfattribs=attribs)
    msp.add_arc((R, H - R), R, 90, 180, dxfattribs=attribs)
    msp.add_line((0, H - R), (0, R), dxfattribs=attribs)
    msp.add_arc((R, R), R, 180, 270, dxfattribs=attribs)

    msp.add_circle((W / 2, H - 15), 6, dxfattribs=attribs)

    doc.saveas(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "cutfiles/sample.dxf"
    build(out)
    print(f"wrote {out}")
