"""Artwork preparation: orientation, cropping, colour mode and resolution."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageOps

from .layout import ImagePlacement

Image.MAX_IMAGE_PIXELS = 500_000_000  # big print files are normal here

JPEG_EXTENSIONS = {".jpg", ".jpeg"}


@dataclass
class PreparedImage:
    image: Image.Image
    #: Set when the artwork can be handed to the PDF writer as a JPEG file, so it
    #: is embedded as-is instead of being re-compressed into a huge Flate blob.
    jpeg_path: str | None
    temp_files: list[str]
    warnings: list[str]


EXIF_ORIENTATION_TAG = 0x0112


def load_image(path: str) -> tuple[Image.Image, bool]:
    """Open `path`, applying any EXIF rotation. Returns (image, was_rotated)."""
    img = Image.open(path)
    img.load()
    try:
        orientation = (img.getexif() or {}).get(EXIF_ORIENTATION_TAG, 1)
    except Exception:
        orientation = 1
    rotated = ImageOps.exif_transpose(img)
    return (rotated or img), orientation not in (None, 1)


def prepare_image(
    path: str,
    placement: ImagePlacement,
    to_cmyk: bool = False,
    max_dpi: float = 600.0,
    background: str = "white",
    jpeg_quality: int | None = 92,
) -> PreparedImage:
    """Crop, flatten, optionally convert to CMYK and cap the resolution."""
    warnings: list[str] = []
    temp_files: list[str] = []
    img, changed = load_image(path)
    original_mode = img.mode

    if placement.crop_px:
        img = img.crop(placement.crop_px)
        changed = True

    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, background)
        flat.paste(rgba, mask=rgba.split()[-1])
        img = flat
        changed = True
        if original_mode in ("RGBA", "LA"):
            warnings.append(f"transparency flattened onto {background}")
    elif img.mode not in ("RGB", "CMYK", "L"):
        img = img.convert("RGB")
        changed = True

    if to_cmyk and img.mode != "CMYK":
        img = img.convert("CMYK")
        changed = True
        warnings.append(
            "converted to CMYK without an ICC profile; for colour-critical work, "
            "supply artwork that is already CMYK"
        )

    if max_dpi and placement.effective_dpi > max_dpi and placement.width_mm > 0:
        factor = max_dpi / placement.effective_dpi
        new_size = (max(1, int(img.width * factor)), max(1, int(img.height * factor)))
        img = img.resize(new_size, Image.LANCZOS)
        changed = True
        warnings.append(
            f"artwork downsampled from {placement.effective_dpi:.0f} to about {max_dpi:.0f} dpi"
        )

    is_jpeg_source = os.path.splitext(path)[1].lower() in JPEG_EXTENSIONS
    jpeg_path: str | None = None
    if not changed and is_jpeg_source:
        jpeg_path = path
    elif changed and is_jpeg_source and jpeg_quality and img.mode in ("RGB", "L"):
        # Re-encoding keeps a photo's PDF a few MB instead of a few dozen.
        # CMYK is deliberately excluded: CMYK JPEG inversion is a known trap.
        fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="kutcontour-")
        os.close(fd)
        img.save(tmp, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)
        jpeg_path = tmp
        temp_files.append(tmp)

    return PreparedImage(img, jpeg_path, temp_files, warnings)


def cleanup(prepared: PreparedImage) -> None:
    for path in prepared.temp_files:
        try:
            os.unlink(path)
        except OSError:
            pass
