import pytest
from app.services.checkout_svc import _extract_esim_details


def test_extracts_from_worldmove_shape():
    """Real captured VivaPe get-esim-by-trx response for a worldmove-type
    product (order 60228, Mainland China 1GB/7D). The real LPA lives under
    qrcodeContent, not a top-level "lpa" key - an earlier version of this
    parser looked for "lpa"/"qr_code" (which don't exist in this response
    at all) and silently fell back to a self-generated fake LPA while
    still marking the order is_mock_fallback=False."""
    esim_data = {
        "esim_order": {"id": 228, "code": 0},
        "iccid": "89862102923600001383",
        "productName": "Mainland China, 7 Days, 1GB, 128kbps",
        "qrcode": "https://esim.joytelecom.com/static/q/20260911/example.png",
        "qrcodeType": 2,
        "resultcode": "000",
        "resultmsg": "Success",
        "qrcodeContent": "LPA:1$rsp.esim.pub$43B1F4B13F7DCCC2062AECA8B6DF4A67",
        "salePlanDays": "7",
    }
    details = _extract_esim_details(esim_data)
    assert details is not None
    assert details["iccid"] == "89862102923600001383"
    assert details["lpa"] == "LPA:1$rsp.esim.pub$43B1F4B13F7DCCC2062AECA8B6DF4A67"
    assert details["smdp"] is None
    assert details["matching_id"] is None


def test_extracts_from_esimgo_shape():
    """Real captured VivaPe get-esim-by-trx response for an esimgo-type
    product (order 60229, UK 1GB/7D). The esim details are nested inside a
    JSON *string* (not object) under esim_order.order - a structurally
    different response shape from worldmove's, returned by the same
    endpoint depending on the underlying supplier VivaPe proxies to."""
    esim_data = {
        "esim_order": {
            "id": 250,
            "orderReference": "85037a9d-e027-4acd-8998-1393a75f484e",
            "status": "completed",
            "statusMessage": "Order completed: 1 eSIMs assigned",
            "order": (
                '[{"esims":[{"iccid":"8943108167004954278",'
                '"matchingId":"4G7KK-ISDQV-YJZYN-NTF8I",'
                '"smdpAddress":"rsp-3104.idemia.io"}],'
                '"type":"bundle","item":"esim_1GB_7D_GB_V2"}]'
            ),
        }
    }
    details = _extract_esim_details(esim_data)
    assert details is not None
    assert details["iccid"] == "8943108167004954278"
    assert details["lpa"] == "LPA:1$rsp-3104.idemia.io$4G7KK-ISDQV-YJZYN-NTF8I"
    assert details["smdp"] == "rsp-3104.idemia.io"
    assert details["matching_id"] == "4G7KK-ISDQV-YJZYN-NTF8I"


@pytest.mark.parametrize("esim_data", [
    {},
    {"error": "Something went wrong"},
    {"esim_order": {"order": "not valid json"}},
    {"esim_order": {"order": "[]"}},
    {"esim_order": {"order": '[{"esims":[]}]'}},
    {"esim_order": {"order": '[{"esims":[{"iccid":"x"}]}]'}},  # missing smdpAddress/matchingId
    "not even a dict",
    None,
])
def test_returns_none_for_unrecognized_shapes(esim_data):
    assert _extract_esim_details(esim_data) is None
