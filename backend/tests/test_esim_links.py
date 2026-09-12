import pytest
from app.services.esim_links import esim_install_links

LPA = "LPA:1$rsp.esim.pub$7C6661C51C6B67EF26D0D622BF625B10"


def test_builds_both_platform_links():
    links = esim_install_links(LPA)
    assert links["ios"].startswith("https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=")
    assert links["android"].startswith("https://esimsetup.android.com/esim_qrcode_provisioning?carddata=")


def test_separators_are_percent_encoded_not_left_as_url_syntax():
    """':' and '$' are data inside the payload, not URL structure - left
    raw, the activation code can be truncated or misread by the client."""
    links = esim_install_links(LPA)
    carddata = links["ios"].split("carddata=", 1)[1]
    assert "$" not in carddata
    assert carddata.startswith("LPA%3A1")
    assert "%24" in carddata  # the $ separators survive as data


@pytest.mark.parametrize("value", [None, "", "   ", "not-an-lpa-string", "89862101151800001226"])
def test_returns_nothing_without_a_usable_activation_string(value):
    """No buttons at all is right when there's nothing to install - a link
    built from a non-LPA value would just dead-end in the system UI."""
    assert esim_install_links(value) == {"ios": None, "android": None}
