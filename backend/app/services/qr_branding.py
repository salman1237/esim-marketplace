"""QR codes with the brand mark in the middle.

A logo sits on top of the code and destroys the modules underneath it, so
this is only safe because of two things together:

- Error correction H, which lets a QR lose about 30% of its modules and
  still decode. The codes here were level M (~15%) before any logo
  existed, which is nowhere near enough to cover the centre.
- A hard cap on how much of the code the logo may cover (LOGO_RATIO).

Get either wrong and the result is a QR that looks fine on screen,
photographs badly, and leaves a paying customer unable to install their
eSIM - with nothing in any log to say why. Hence test_qr_branding.py,
which decodes every generated code rather than trusting that it looks
right.
"""
import io
from typing import Optional

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H
from qrcode.image.pil import PilImage

from app.core.logging import get_logger

logger = get_logger(__name__)

# Share of the QR's width the logo disc may occupy. 0.22 keeps the covered
# area near 4% of the code - comfortably inside what level H can rebuild,
# with room left for a scuffed print or an awkward camera angle. Raising
# this is how a QR stops scanning in the real world while still decoding
# from a clean screenshot.
LOGO_RATIO = 0.22

# Named so a test can assert it. The margin this buys is the only reason a
# logo is acceptable at all, and it is invisible in a clean screenshot:
# a code built at M with this logo still decodes perfectly on screen and
# then fails off a creased printout.
ERROR_CORRECTION = ERROR_CORRECT_H

# White ring around the logo, as a share of the disc. Without it the logo
# blends into the modules and the scanner loses the boundary.
RING_RATIO = 0.12


def _circular(logo: Image.Image, size: int) -> Image.Image:
    """The logo on a white disc, masked to a circle."""
    disc = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(disc)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(255, 255, 255, 255))

    inner = max(1, int(size * (1 - RING_RATIO * 2)))
    art = logo.convert("RGBA")
    # Fit inside the disc without distorting it - a squashed logo looks
    # worse than no logo.
    art.thumbnail((inner, inner), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    disc.paste(art, ((size - art.width) // 2, (size - art.height) // 2), art)
    disc.putalpha(mask)
    return disc


def qr_png(payload: str, logo_bytes: Optional[bytes] = None, *, box_size: int = 10) -> Optional[bytes]:
    """PNG for an eSIM activation string, with the brand mark centred when
    a logo is supplied. Returns None rather than raising: a missing QR must
    never stop a delivery email, which also carries the activation code as
    copyable text.

    A logo that cannot be read is skipped and the plain QR is returned -
    the code matters, the decoration does not.
    """
    try:
        qr = qrcode.QRCode(error_correction=ERROR_CORRECTION, box_size=box_size, border=4)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(image_factory=PilImage).convert("RGBA")

        if logo_bytes:
            try:
                logo = Image.open(io.BytesIO(logo_bytes))
                size = int(img.width * LOGO_RATIO)
                disc = _circular(logo, size)
                img.paste(disc, ((img.width - size) // 2, (img.height - size) // 2), disc)
            except Exception as e:
                logger.warning("qr_logo_skipped", error=str(e))

        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("qr_generation_failed", error=str(e))
        return None
