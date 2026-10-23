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
    # smdp/matching_id come from parsing the LPA itself, not placeholders.
    assert details["smdp"] == "rsp.esim.pub"
    assert details["matching_id"] == "43B1F4B13F7DCCC2062AECA8B6DF4A67"


def test_extracts_from_worldmove_shape_nested_under_esim_order():
    """Real captured production response (trx 60273, Singapore/Malaysia
    3GB/7D) that a top-level-only parser refunded despite VivaPe having
    successfully issued and charged for the eSIM: here iccid and
    qrcodeContent live INSIDE esim_order, not at the top level."""
    esim_data = {
        "esim_order": {
            "id": 269,
            "code": 0,
            "orderId": "b0001cd2609110061",
            "iccid": "89862101151800001226",
            "productName": "Singapore, Malaysia, 7 Days, 3GB, 128kbps",
            "qrcode": "https://esim.joytelecom.com/static/q/20260911/example.png",
            "resultcode": "000",
            "resultmsg": "Success",
            "qrcodeContent": "LPA:1$rsp.esim.pub$7C6661C51C6B67EF26D0D622BF625B10",
            "salePlanDays": "7",
            "purchase_id": 60273,
            "note": "World Move eSIM Transaction Redeem",
        }
    }
    details = _extract_esim_details(esim_data)
    assert details is not None
    assert details["iccid"] == "89862101151800001226"
    assert details["lpa"] == "LPA:1$rsp.esim.pub$7C6661C51C6B67EF26D0D622BF625B10"
    assert details["smdp"] == "rsp.esim.pub"
    assert details["matching_id"] == "7C6661C51C6B67EF26D0D622BF625B10"


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


def test_extracts_from_telna_shape():
    """Real captured VivaPe get-esim-by-trx response for a telna-type
    product (trx 60401, "VivaPe Test - 500MB - BGD - 7 Days") from an
    actual live purchase on 2026-10-23, run specifically to verify Telna
    support before any real customer could reach it. The first attempt
    refunded this exact purchase despite VivaPe having genuinely issued
    and charged for the eSIM (ICCID 8910300000064674263) - this parser had
    no shape that matched iccid/smdpAddress/matchingId sitting directly on
    esim_order, a structure distinct from both worldmove's (qrcodeContent)
    and esimgo's (a JSON-string-wrapped order/esims array)."""
    esim_data = {
        "esim_order": {
            "id": 1,
            "order_reference": "TLN-ORD-GFDOU23MJJ",
            "iccid": "8910300000064674263",
            "package_id": "e399ef27-4896-4faa-ac0f-19de9cc4240d",
            "package_template_id": "21701498",
            "purchase_transaction_id": 60401,
            "sku": "TELNA-BGD-500MB-7D",
            "product_name": "VivaPe Test - 500MB - BGD - 7 Days",
            "data_allowance_bytes": 524288000,
            "activation_code": "LPA:1$consumer.e-sim.global$TN20260608094433A7B7962F",
            "direct_apple_url": "https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA%3A1%24consumer.e-sim.global%24TN20260608094433A7B7962F",
            "status": "active",
            "smdpAddress": "consumer.e-sim.global",
            "matchingId": "TN20260608094433A7B7962F",
            "qr_code_url": "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=LPA%3A1%24consumer.e-sim.global%24TN20260608094433A7B7962F",
            "profile_state": "active",
        }
    }
    details = _extract_esim_details(esim_data)
    assert details is not None
    assert details["iccid"] == "8910300000064674263"
    assert details["lpa"] == "LPA:1$consumer.e-sim.global$TN20260608094433A7B7962F"
    assert details["smdp"] == "consumer.e-sim.global"
    assert details["matching_id"] == "TN20260608094433A7B7962F"
    # Telna's own "activation_code" is already the same string - confirms
    # the two never disagree, though it is matchingId/smdpAddress that are
    # actually trusted, not activation_code itself.
    assert details["lpa"] == esim_data["esim_order"]["activation_code"]


def test_telna_shape_requires_all_three_fields_not_just_iccid():
    """esim_order.iccid alone must not be enough to match the telna shape -
    an incomplete/partial response (e.g. mid-provisioning) must fall
    through to None and refund, not synthesize an LPA from missing parts."""
    assert _extract_esim_details({"esim_order": {"iccid": "8910300000064674263"}}) is None
    assert _extract_esim_details({"esim_order": {"iccid": "x", "smdpAddress": "y"}}) is None  # no matchingId


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
