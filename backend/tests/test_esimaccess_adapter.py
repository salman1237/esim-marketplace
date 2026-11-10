"""See backend/docs/esimaccess_integration_reference.md for the research
behind every assumption this file locks down - auth (RT-AccessCode only,
confirmed live), the always-200/business-error-in-body response envelope
(the same trap VivaPe already cost this project real money on once), and
the Day Pass tiered-discount pricing formula (price != daily_rate * days).
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.esimaccess_adapter import (
    ESIMAccessAdapter,
    ESIMAccessError,
    day_pass_total_price,
    decimal_to_scaled,
    scaled_to_decimal,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_esimaccess():
    """Overrides conftest's autouse mock_esimaccess, which patches
    ESIMAccessAdapter.create_order/query_esim globally - this file tests
    those real implementations directly (via a mocked httpx.AsyncClient
    instead, at a lower level), so they must not be patched away here.
    Exact same reasoning as test_vivape_adapter.py's own override of
    conftest's mock_vivape."""
    yield


def _resp(json_body, status_code=200, text=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    r.text = text if text is not None else str(json_body)
    return r


def _client_returning(resp):
    mock_client = AsyncMock()
    mock_client.post.return_value = resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    return mock_client


# --- money encoding ----------------------------------------------------------

def test_scaled_to_decimal_divides_by_ten_thousand():
    """70000 == $7.00, confirmed live against the real balance/query call
    (500000 == $50.00) and the official top-up example (70000 == $7.00) -
    never 2-decimal cents."""
    assert scaled_to_decimal(70000) == Decimal("7.0000")
    assert scaled_to_decimal(500000) == Decimal("50.0000")
    assert scaled_to_decimal(7000) == Decimal("0.7000")


def test_decimal_to_scaled_is_the_inverse():
    assert decimal_to_scaled(Decimal("7.00")) == 70000
    assert decimal_to_scaled(Decimal("0.70")) == 7000


# --- Day Pass tiered pricing - the gotcha the reference doc calls out loudest ---

def test_day_pass_price_is_not_daily_rate_times_days():
    """The China worked example in the reference doc: $0.65/day (6500
    scaled) for a 7-day purchase. Flat multiplication would give 45500
    (=$4.55); the real tiered formula (7 days -> the 5-9 day band -> 92%
    of the daily rate) gives 41860 (=$4.186, which the doc's prose rounds
    to "$4.19" for readability - this test checks the exact arithmetic,
    not the rounded figure)."""
    flat_multiplication = 6500 * 7
    assert flat_multiplication == 45500  # what NOT doing this would give
    assert day_pass_total_price(6500, 7) == 41860
    assert day_pass_total_price(6500, 7) != flat_multiplication


@pytest.mark.parametrize("period_num,expected_share", [
    (1, Decimal("0.96")), (4, Decimal("0.96")),
    (5, Decimal("0.92")), (9, Decimal("0.92")),
    (10, Decimal("0.89")), (19, Decimal("0.89")),
    (20, Decimal("0.85")), (29, Decimal("0.85")),
    (30, Decimal("0.82")), (365, Decimal("0.82")),
])
def test_day_pass_band_boundaries(period_num, expected_share):
    """Every band boundary from the reference doc's table, both ends -
    an off-by-one here would silently charge the wrong tier right at a
    boundary, which is exactly where a boundary bug hides."""
    daily_rate = 10000  # a clean $1.00/day makes the expected result obvious
    assert day_pass_total_price(daily_rate, period_num) == int(daily_rate * period_num * expected_share)


def test_day_pass_beyond_confirmed_range_raises_rather_than_guesses():
    """No band in the reference doc covers more than 365 days. Silently
    applying the longest-stay discount to, say, a 400-day purchase would be
    an unverified guess baked into a real charge - fail loudly instead."""
    with pytest.raises(ValueError, match="366"):
        day_pass_total_price(10000, 366)


# --- call_api: the always-200/business-error-in-body trap --------------------

async def test_call_api_raises_on_business_failure_despite_http_200(db_session):
    """The exact trap vivape_adapter.py's create_transaction() comment
    documents paying for in real money once already, on a different
    supplier: HTTP 200 is not success. success: false must raise, not be
    silently treated as a usable result."""
    resp = _resp({"success": False, "errorCode": "200010", "errorMsg": "eSIM still being allocated"})
    with patch("httpx.AsyncClient", return_value=_client_returning(resp)):
        with pytest.raises(ESIMAccessError, match="200010"):
            await ESIMAccessAdapter.call_api(db_session, "esim/query", data={"iccid": "123"})


async def test_call_api_raises_on_non_200_http_status(db_session):
    resp = _resp({"error": "unauthorized"}, status_code=401)
    with patch("httpx.AsyncClient", return_value=_client_returning(resp)):
        with pytest.raises(ESIMAccessError, match="401"):
            await ESIMAccessAdapter.call_api(db_session, "balance/query")


async def test_call_api_returns_body_on_real_success(db_session):
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"balance": 500000}})
    with patch("httpx.AsyncClient", return_value=_client_returning(resp)):
        result = await ESIMAccessAdapter.call_api(db_session, "balance/query")
    assert result["obj"]["balance"] == 500000


async def test_call_api_sends_only_the_access_code_header_no_signature(db_session):
    """Confirmed live (reference doc §2): RT-AccessCode alone is sufficient,
    no HMAC/timestamp/signature header. Pins the adapter to that confirmed
    shape so a future change doesn't silently add signing nobody asked for
    without it being a deliberate, visible decision."""
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"balance": 0}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        await ESIMAccessAdapter.call_api(db_session, "balance/query")

    _, kwargs = client.post.call_args
    headers = kwargs["headers"]
    assert "RT-AccessCode" in headers
    assert not any(h.lower().startswith("rt-") and h.lower() != "rt-accesscode" for h in headers)


async def test_every_call_is_audit_logged_with_esimaccess_as_supplier_name(db_session):
    """Mirrors vivape_adapter.py's logging discipline, with the discriminator
    value the reference doc's §7 specifies - no schema change needed, this
    is the only thing that has to be right.

    Asserts on this call's own distinguishing response payload rather than a
    row count: every test in this file that calls call_api() commits a real
    SupplierTransactionLog row to the shared test DB with no per-test
    rollback, so other tests' rows are already present by the time this one
    runs - a bare count would be order-dependent in exactly the way
    test_supplier_settings.py's own tests already learned not to be."""
    from sqlalchemy import select
    from app.models.audit import SupplierTransactionLog

    sentinel_balance = 918273645  # distinguishes this row from any other test's
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"balance": sentinel_balance}})
    with patch("httpx.AsyncClient", return_value=_client_returning(resp)):
        await ESIMAccessAdapter.call_api(db_session, "balance/query")

    rows = (await db_session.execute(
        select(SupplierTransactionLog)
        .where(SupplierTransactionLog.supplier_name == "ESIMACCESS")
        .where(SupplierTransactionLog.endpoint == "balance/query")
    )).scalars().all()
    matching = [r for r in rows if isinstance(r.response_payload, dict)
                and (r.response_payload.get("obj") or {}).get("balance") == sentinel_balance]
    assert len(matching) == 1
    assert matching[0].method == "POST"


# --- per-endpoint wiring ------------------------------------------------------

async def test_get_balance_returns_a_real_decimal_amount(db_session):
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"balance": 500000}})
    with patch("httpx.AsyncClient", return_value=_client_returning(resp)):
        balance = await ESIMAccessAdapter.get_balance(db_session)
    assert balance == Decimal("50.0000")


async def test_list_packages_empty_location_code_means_the_whole_catalogue(db_session):
    """Confirmed this is how the real 3,259-package pull was taken
    (reference doc §4.1) - an empty/unfiltered call, not a per-country loop
    assembled client-side."""
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None,
                  "obj": {"packageList": [{"packageCode": "A"}, {"packageCode": "B"}]}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        packages = await ESIMAccessAdapter.list_packages(db_session)

    assert len(packages) == 2
    _, kwargs = client.post.call_args
    assert kwargs["json"]["locationCode"] == ""


async def test_create_order_sends_transaction_id_in_the_body_not_a_header(db_session):
    """The concrete question the reference doc set out to pin down: this is
    the idempotency key, and it goes in the request body (esim/order),
    unlike VivaPe which has no idempotency key at all."""
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"orderNo": "ORD123"}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        result = await ESIMAccessAdapter.create_order(
            db_session, transaction_id="txn-abc-123", package_code="TOPUP_CKH491", amount_scaled=70000
        )

    assert result["orderNo"] == "ORD123"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["transactionId"] == "txn-abc-123"
    assert "transactionId" not in kwargs["headers"]
    assert kwargs["json"]["packageInfoList"] == [{"packageCode": "TOPUP_CKH491", "count": 1}]


async def test_create_order_includes_period_num_for_a_day_pass(db_session):
    """periodNum (the Day Pass duration in days) is required to buy the
    right duration - omitted entirely for fixed-data orders (confirmed
    live without it), included only when the caller actually passes one."""
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"orderNo": "ORD456"}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        await ESIMAccessAdapter.create_order(
            db_session, transaction_id="txn-daypass-1", package_code="P7YECLII9",
            amount_scaled=57960, period_num=7,
        )
    _, kwargs = client.post.call_args
    assert kwargs["json"]["packageInfoList"] == [{"packageCode": "P7YECLII9", "count": 1, "periodNum": 7}]


async def test_create_order_omits_period_num_for_fixed_data(db_session):
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"orderNo": "ORD789"}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        await ESIMAccessAdapter.create_order(
            db_session, transaction_id="txn-fixed-1", package_code="CKH002", amount_scaled=16000,
        )
    _, kwargs = client.post.call_args
    assert "periodNum" not in kwargs["json"]["packageInfoList"][0]


async def test_create_order_rejects_a_transaction_id_over_fifty_chars(db_session):
    with pytest.raises(ValueError, match="50"):
        await ESIMAccessAdapter.create_order(
            db_session, transaction_id="x" * 51, package_code="ANY", amount_scaled=1000
        )


async def test_cancel_refunds_an_unused_profile(db_session):
    """The capability VivaPe has no equivalent of at all - this is what
    would have prevented the EUR28.61 lost-to-abandoned-eSIMs incident on
    VivaPe, documented in the supplier comparison work."""
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None, "obj": {"iccid": "89852245280001354019"}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        await ESIMAccessAdapter.cancel_esim(db_session, iccid="89852245280001354019")

    args, kwargs = client.post.call_args
    assert args[0].endswith("esim/cancel")
    assert kwargs["json"] == {"iccid": "89852245280001354019"}


async def test_query_esim_by_order_no(db_session):
    resp = _resp({"success": True, "errorCode": "0", "errorMsg": None,
                  "obj": {"iccid": "89852245280001354019", "totalVolume": 5368709120, "orderUsage": 907415004}})
    client = _client_returning(resp)
    with patch("httpx.AsyncClient", return_value=client):
        result = await ESIMAccessAdapter.query_esim(db_session, order_no="ORD123")

    assert result["iccid"] == "89852245280001354019"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["orderNo"] == "ORD123"
    assert kwargs["json"]["pager"] == {"pageNum": 1, "pageSize": 20, "total": None}
