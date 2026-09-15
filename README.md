# KutContour

Makes the PDF a laser cutter wants: your artwork on a 263 × 303 mm page with a
**CutContour** cut line on top — a real spot colour, 100% magenta, 1 pt, set to
overprint. It reuses the same DXF cut file every time, so ordering branding is
"drop in the new image, download the PDF" instead of an Illustrator subscription.

## What ends up in the PDF

| | |
|---|---|
| Page | 263 × 303 mm (1.5 mm bleed around a 260 × 300 mm cut) |
| Cut line | Separation colour named `CutContour`, alternate space DeviceCMYK 0/100/0/0 |
| Stroke | 1 pt, overprint on (`/OP true`) |
| Layers | Two PDF layers, `Artwork` and `CutContour`, so the cutter can isolate the path |
| Boxes | MediaBox = page, TrimBox = the cut line's bounds, BleedBox = page |
| Artwork | Placed under the cut line, filling the page including the bleed |

That is the same structure Illustrator produces for a spot-colour cut path, built
directly instead.

## Install

**Windows (PowerShell)** — one command per line; `&&` is not a separator in
Windows PowerShell 5.1:

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\Activate.ps1
```

If that last line is refused with "running scripts is disabled on this system",
either allow it once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or skip activating and
spell out `.venv\Scripts\kutcontour` in place of `kutcontour` below.

**macOS / Linux:**

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
source .venv/bin/activate
```

Then put your DXF in `cutfiles/`. With one file in there, nothing needs naming:

```powershell
Copy-Item C:\path\to\your-cut.dxf cutfiles\   # Windows
```

```bash
cp /path/to/your-cut.dxf cutfiles/              # macOS / Linux
```

No cut file yet? `python examples/make_sample_dxf.py cutfiles/sample.dxf` writes a
260 × 300 mm rounded rectangle with a hanging hole to practise on.

The commands below assume the virtual environment is active. Without it, put
`.venv\Scripts\` (Windows) or `.venv/bin/` (macOS / Linux) in front of
`kutcontour` and `python`.

## Use it

**In the browser** — the everyday way:

```bash
kutcontour serve          # http://127.0.0.1:5000
```

Drag the image in, then place it against the cut line: **drag the artwork in the
preview to move it, scroll over it to zoom**, or type exact millimetres into the
Left/right and Up/down boxes. Everything outside the cut line is veiled, so you
can see the shape that actually survives. The readout under the preview tracks
the zoom, the offset, the size on the page and the resolution — which turns red
below 150 dpi, before you have committed to anything.

The preview is the real placement: the browser uses the same maths as the PDF
writer, so what you see is what the cutter gets.

**From the command line** — the scriptable way:

```bash
kutcontour build -i artwork.jpg -o banner.pdf
kutcontour build -i artwork.jpg -o banner.pdf --preview check.png
kutcontour build -i artwork.jpg -o banner.pdf --scale 0.8 --offset-y -12
```

```
wrote banner.pdf
  page        263 x 303 mm
  cut line    260 x 300 mm (2 paths, 2 closed)
  bleed       1.5 / 1.5 mm
  spot colour CutContour, 1 pt, overprint
  artwork     312 dpi at final size
```

## The other commands

```bash
kutcontour inspect                    # what is in the cut file: paths, size, units
kutcontour template -o guide.png      # a PNG of the page with the cut line on it
kutcontour verify banner.pdf          # re-read a finished PDF and check it
```

`template` is the one to hand to whoever designs the artwork: it shows the cut
line and a dashed safe area on a correctly sized page. Design at 263 × 303 mm,
run the background all the way to the edge, keep anything that must survive the
cut inside the dashed line.

`verify` exits non-zero if the spot colour or the overprint flag is missing, so it
works as a last check in a script.

## Options worth knowing

| Option | Does |
|---|---|
| `--image-fit cover\|contain\|stretch` | the starting size before `--scale`: `cover` (default) fills the page, `contain` fits the whole image, `stretch` distorts |
| `--scale 0.8` | zoom the artwork; 1.0 is the plain fit, below 1 shrinks it |
| `--offset-x 12` / `--offset-y -8` | move the artwork in mm; x is right, y is up |
| `--image-align top\|bottom\|left\|right` | which part of the image survives a `cover` crop, before any offset |
| `--fit` | scale an oversized cut line down to the maximum instead of just warning |
| `--no-center` | keep the DXF's own coordinates rather than centring on the page |
| `--units mm\|cm\|in` | override the DXF's `$INSUNITS`, for files saved as unitless |
| `--layer NAME` | read only this DXF layer (repeatable) |
| `--stroke 0.25` | a different cut line width in points |
| `--spot-name Thru-cut` | a different spot colour name, if your printer uses one |
| `--page 320x450 --max-cut 317x447` | a different format |
| `--cmyk` | convert the artwork to CMYK — see the warning below |
| `--max-dpi 600` | downsample artwork above this resolution (keeps PDFs sane) |

## Things the tool will tell you about

It warns rather than silently fixing, because a quietly resized cut file is worse
than a loud one:

- artwork below 150 dpi at final size, or largely moved outside the page
- artwork that no longer covers the page, so the uncovered edge would print white
- a cut line larger than the maximum, or with less than 1.5 mm of bleed around it
- open contours — a cutter usually wants closed paths
- unsupported DXF entities that were skipped (text, dimensions, hatches)

## Notes

**Units.** DXF files often carry no unit at all. The tool assumes millimetres and
says so; `kutcontour inspect` shows the size it read, which is the fastest way to
catch a file that was actually drawn in inches.

**Loose segments.** Cut files are often exported as separate lines and arcs rather
than one polyline. They are stitched back into closed paths automatically
(endpoints within 0.05 mm), so the PDF gets real closed contours.

**CMYK.** `--cmyk` uses a naive conversion with no ICC profile. For colour-critical
work, supply artwork that is already CMYK, or leave it in RGB and let the printer's
RIP convert — most prefer that.

**Overprint** is on by default and is what stops the magenta cut line knocking a
white gap out of the artwork underneath it. Leave it on unless your printer asks
otherwise.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

The suite builds real PDFs and reads them back with pikepdf to confirm the
separation, the overprint flag, the layers, the page size and the trim box.
