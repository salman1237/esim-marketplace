"""A QR with a logo on it must still scan.

The logo sits on top of the code and destroys the modules underneath. It
only works because the code is generated at error-correction H and the
mark is capped at a fraction of the width - and both of those are easy to
undo later without noticing, because the result still LOOKS like a QR.

So these tests decode the generated image rather than inspecting it. The
failure being guarded against is a customer who paid, received a tidy
branded QR, and cannot install their eSIM - with nothing in any log to
explain why.
"""
import io

import pytest
from PIL import Image, ImageDraw

from app.services.qr_branding import LOGO_RATIO, qr_png

cv2 = pytest.importorskip("cv2", reason="needs a QR decoder to prove the code still scans")
import numpy as np  # noqa: E402  (only meaningful once cv2 is present)

LPA = "LPA:1$rsp.truphone.com$QR-CODE-TEST-7F3A91C2E8"


def _logo(size: int = 512, colour=(14, 165, 233, 255)) -> bytes:
    """Stand-in for the uploaded brand logo."""
    img = Image.new("RGBA", (size, size), colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _decode(png: bytes) -> str:
    array = np.frombuffer(png, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return value


def test_a_plain_qr_decodes():
    """Baseline: if this fails, nothing below means anything."""
    assert _decode(qr_png(LPA)) == LPA


def test_a_branded_qr_still_decodes():
    """The whole point. A logo that breaks the code is worse than no logo."""
    assert _decode(qr_png(LPA, _logo())) == LPA


def test_a_branded_qr_decodes_at_the_size_emails_render():
    """The delivery email shows the QR at 220px. A code that only decodes
    at full resolution is no use to someone scanning it off a phone."""
    png = qr_png(LPA, _logo())
    shrunk = Image.open(io.BytesIO(png)).resize((220, 220), Image.LANCZOS)
    buf = io.BytesIO()
    shrunk.save(buf, format="PNG")
    assert _decode(buf.getvalue()) == LPA


def test_a_long_activation_string_still_decodes_with_a_logo():
    """A denser code has smaller modules, so the logo covers more of them.
    Real LPA strings vary a lot in length between suppliers."""
    long_lpa = "LPA:1$consumer.rsp.a-very-long-smdp-hostname.example.com$" + "A1B2C3D4E5" * 6
    assert _decode(qr_png(long_lpa, _logo())) == long_lpa


def test_an_unreadable_logo_falls_back_to_a_plain_qr():
    """The code matters, the decoration does not: a corrupt logo file must
    not cost the customer their eSIM."""
    png = qr_png(LPA, b"this is not an image")
    assert png is not None
    assert _decode(png) == LPA


def test_the_logo_is_actually_drawn():
    """Guards the opposite failure - a 'branded' QR that silently has no
    brand on it would make every test above pass for the wrong reason."""
    plain = qr_png(LPA)
    branded = qr_png(LPA, _logo())
    assert plain != branded

    centre = Image.open(io.BytesIO(branded)).convert("RGB")
    px = centre.getpixel((centre.width // 2, centre.height // 2))
    # The stand-in logo is sky blue; a bare QR centre is black or white.
    assert px not in ((0, 0, 0), (255, 255, 255))


def test_the_logo_stays_within_its_cap():
    """LOGO_RATIO is the safety margin. If someone raises it to make the
    mark look bigger, this says so before a customer finds out."""
    assert LOGO_RATIO <= 0.25, "a larger mark risks codes that scan on screen but not on paper"


@pytest.mark.parametrize("box_size", [4, 8, 10, 16])
def test_it_decodes_across_the_render_sizes(box_size):
    """Printed sheets, emails and phone screens all render differently."""
    assert _decode(qr_png(LPA, _logo(), box_size=box_size)) == LPA


def test_the_code_is_built_at_the_highest_error_correction():
    """Structural guard. Level H is what buys the headroom the logo spends."""
    from qrcode.constants import ERROR_CORRECT_H

    from app.services import qr_branding

    assert qr_branding.ERROR_CORRECTION == ERROR_CORRECT_H


def test_a_branded_qr_survives_real_world_damage():
    """The behavioural version, and the one that actually bites.

    Dropping back to error correction M still decodes a branded QR from a
    clean image - so every other test here passes while the margin that
    makes the logo safe has quietly gone. Scuffing the code the way a
    folded printout or a thumbprint would is what tells the difference.
    """
    png = qr_png(LPA, _logo())
    img = Image.open(io.BytesIO(png)).convert("RGB")

    # A scuff across a corner, clear of the finder patterns - the sort of
    # damage level H is specifically there to absorb.
    draw = ImageDraw.Draw(img)
    w, h = img.size
    draw.rectangle((int(w * 0.55), int(h * 0.55), int(w * 0.78), int(h * 0.78)), fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert _decode(buf.getvalue()) == LPA, (
        "a branded QR could not absorb ordinary damage - error correction is too low for the logo"
    )
