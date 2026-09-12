"""Universal "one tap install" links for an eSIM activation string.

Both platforms accept the same GSMA LPA payload on a vendor-hosted
universal link, which opens the system eSIM installer directly - no QR
scan, no manual typing:

    iOS 17.4+   https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=...
    Android     https://esimsetup.android.com/esim_qrcode_provisioning?carddata=...
                (rolled out January 2026, so device support is still uneven)

Support is not universal, which is why the QR code and the copyable
activation code stay on every surface that shows these buttons.

Shared by the delivery email and the customer portal so the two can't
drift apart.
"""
from urllib.parse import quote

IOS_UNIVERSAL_LINK = "https://esimsetup.apple.com/esim_qrcode_provisioning?carddata="
ANDROID_UNIVERSAL_LINK = "https://esimsetup.android.com/esim_qrcode_provisioning?carddata="


def esim_install_links(lpa_string: str | None) -> dict[str, str | None]:
    """Returns {"ios": url, "android": url}, both None when there's no
    usable activation string to build them from."""
    if not lpa_string or not lpa_string.strip().upper().startswith("LPA:"):
        return {"ios": None, "android": None}

    # The payload carries ':' and '$' separators, which must survive as
    # data rather than being read as URL syntax.
    carddata = quote(lpa_string.strip(), safe="")
    return {
        "ios": f"{IOS_UNIVERSAL_LINK}{carddata}",
        "android": f"{ANDROID_UNIVERSAL_LINK}{carddata}",
    }
