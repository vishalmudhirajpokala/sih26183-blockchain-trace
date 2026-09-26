"""
Build the BlockTrace brand assets from the supplied 2000x2000 logo plate.

Run from the repo root:  python tools/build_brand_assets.py

The source is a square plate with the horizontal lockup floating in the middle
of it, on a flat near-white background, with no alpha channel. Shipping it as
is would put a white rectangle on a dark sidebar and waste most of the file on
padding, so four things happen here:

  1. Crop        to the real content bounds
  2. Key         the background to transparent, with a soft ramp
  3. Split       the monogram from the wordmark at the widest empty column gap
  4. Resize      to the sizes the UI actually renders, twice over for retina

Everything is derived from one source file. Nothing is redrawn, so the mark
cannot drift from the artwork.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

SOURCE = r"C:/Users/VISHAL/Downloads/BlockTrace logo system/1.png"
BRAND_DIR = r"C:/Users/VISHAL/sih26183-prototype/frontend/public/brand"
PUBLIC_DIR = r"C:/Users/VISHAL/sih26183-prototype/frontend/public"

# Below this the weakest channel is dark enough to be ink, so the pixel is
# fully opaque. Above it the pixel is background. Between them the alpha ramps,
# which is what keeps the curves on the B from turning into stair-steps -- a
# hard threshold leaves visible jaggies at 32px.
INK_MAX = 222
CLEAR_MIN = 250


def key_out_background(image: Image.Image) -> Image.Image:
    """Make the flat background transparent.

    The test is on the *minimum* channel, not on "is this white". White has all
    three channels high, so its minimum is high. The logo's lightest blue is
    still around 0x4a in its weakest channel, so its minimum is low and it
    survives. One number separates background from light-blue ink without
    touching a hue.
    """
    arr = np.asarray(image.convert("RGBA")).astype(np.float32)
    weakest = arr[:, :, :3].min(axis=2)

    span = float(CLEAR_MIN - INK_MAX)
    alpha = np.clip((CLEAR_MIN - weakest) / span, 0.0, 1.0) * 255.0

    arr[:, :, 3] = alpha
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def lift_for_dark_surface(image: Image.Image) -> Image.Image:
    """
    A version for the dark shell.

    The wordmark and parts of the monogram are a near-black navy that would be
    invisible against the sidebar. Those pixels are lifted to white. The two
    blues are left alone, because the brand's blue is the part that has to
    survive -- recolouring it would be inventing a logo that does not exist.
    """
    arr = np.asarray(image.convert("RGBA")).astype(np.float32)
    rgb = arr[:, :, :3]
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]

    dark_ink = lum < 95
    mid_blue = (lum >= 95) & (lum < 150)
    # Lift the mid blue one step so it separates from the background without
    # becoming the same white as the ink.
    lift = ((150.0 - lum) / 55.0)[:, :, None]
    rgb = np.where(mid_blue[:, :, None], rgb + (255.0 - rgb) * lift, rgb)
    rgb = np.where(dark_ink[:, :, None], 255.0, rgb)

    arr[:, :, :3] = np.clip(rgb, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def split_lockup(image: Image.Image) -> tuple[Image.Image, int]:
    """Cut the monogram off at the widest run of empty columns."""
    alpha = np.asarray(image.split()[3])
    opaque_cols = (alpha > 8).any(axis=0)

    gap_len = 0
    gap_start = 0
    run = 0
    for x, filled in enumerate(list(opaque_cols) + [True]):
        if filled:
            if run > gap_len:
                gap_len, gap_start = run, x - run
            run = 0
        else:
            run += 1

    if gap_len == 0:
        return image, 0
    return image.crop((0, 0, gap_start, image.size[1])), gap_start


def save(image: Image.Image, path: str, width: int) -> int:
    ratio = image.size[1] / image.size[0]
    resized = image.resize((width, max(1, round(width * ratio))), Image.LANCZOS)
    resized.save(path, optimize=True)
    return os.path.getsize(path)


def main() -> int:
    os.makedirs(BRAND_DIR, exist_ok=True)

    plate = Image.open(SOURCE).convert("RGBA")
    keyed = key_out_background(plate)
    lockup = keyed.crop(keyed.getbbox())
    mark, _ = split_lockup(lockup)

    outputs = [
        # Two bytes per CSS pixel, so the mark is sharp on a retina display
        # where the sidebar renders it at 28px.
        ("blocktrace-mark.png", mark, 128),
        ("blocktrace-mark-on-dark.png", lift_for_dark_surface(mark), 128),
        ("blocktrace-lockup.png", lockup, 480),
        ("blocktrace-lockup-on-dark.png", lift_for_dark_surface(lockup), 480),
    ]
    for name, image, width in outputs:
        path = os.path.join(BRAND_DIR, name)
        size = save(image, path, width)
        print(f"  {name:<34} {image.size[0]}px source -> {width}px  {size:>7,} b")

    # Favicons: the monogram alone, padded so the outer ring is not flush to
    # the edge of the tab.
    pad = int(mark.size[0] * 0.10)
    padded = Image.new("RGBA", (mark.size[0] + pad * 2, mark.size[1] + pad * 2), (0, 0, 0, 0))
    padded.paste(mark, (pad, pad), mark)
    for name, edge in [
        ("favicon.png", 64),
        ("apple-touch-icon.png", 180),
        ("brand/favicon-256.png", 256),
    ]:
        path = os.path.join(PUBLIC_DIR, name)
        padded.resize((edge, edge), Image.LANCZOS).save(path, optimize=True)
        print(f"  {name:<34} {edge}x{edge}  {os.path.getsize(path):>7,} b")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
