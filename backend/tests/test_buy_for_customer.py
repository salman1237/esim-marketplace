"""Selling an eSIM to a customer who has no account yet.

The reported bug: a merchant typed a real customer email and phone, and
the system threw the email away and invented
user_<random>@customer.esim.local instead. The delivery email went to a
domain that does not exist, the order showed a meaningless name, and the
customer could never sign in to see what they had paid for.

So these tests are about one thing: the email the merchant typed is the
account the customer gets.
"""
from decimal import Decimal

import uuid

import pytest
from sqlalchemy import func, select

from app.models.order import Order
from app.models.user import User
from app.services.email_svc import EmailService
from conftest import create_test_product, fund_wallet, register_and_login

pytestmark = pytest.mark.asyncio

# Generated, never literal: these are fixture values, but a hardcoded
# "new_password": "..." is indistinguishable from a leaked credential to a
# secret scanner, and a test that trips the scanner on every commit trains
# everyone to wave the scanner through.
CHOSEN_PW = f"pw-{uuid.uuid4().hex[:14]}"
WRONG_PW = f"no-{uuid.uuid4().hex[:14]}"

# Phone numbers the merchant types in; each also becomes that customer's
# first password, which is the behaviour under test.
PHONE_LOGIN = "01711-223355"
PHONE_LOCKED = "01755555555"
PHONE_VIEWER = "01766666666"
PHONE_UNLOCK = "01777777777"
PHONE_WRONGPW = "01788888888"


@pytest.fixture
def captured_account_emails(monkeypatch):
    """SMTP is not configured in tests, so capture the call instead."""
    sent = []

    async def _capture(cls_db, to_email, **kwargs):
        sent.append({"to": to_email, **kwargs})
        return True

    monkeypatch.setattr(EmailService, "send_account_created", classmethod(
        lambda cls, db, to_email, **kw: _capture(db, to_email, **kw)
    ))
    return sent


async def _merchant(client, db_session, promote_role, name="shopkeeper"):
    merchant = await register_and_login(client, name)
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("200.0000"))
    return merchant


async def _sell_to(client, merchant, product, *, email, phone=None):
    body = {
        "product_id": product.id, "payment_method": "WALLET",
        "is_buy_for_user": True, "auto_create_user": True,
        "beneficiary_email": email,
    }
    if phone:
        body["beneficiary_phone"] = phone
    return await client.post("/api/v1/orders/checkout", json=body, headers=merchant["headers"])


async def test_the_customer_account_uses_the_email_the_merchant_typed(
    client, db_session, promote_role, captured_account_emails
):
    """The whole bug in one assertion."""
    merchant = await _merchant(client, db_session, promote_role)
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    res = await _sell_to(client, merchant, product, email="traveller@example.com", phone="+8801711223344")
    assert res.status_code == 202, res.text

    beneficiary = (await db_session.execute(
        select(User).where(User.id == res.json()["beneficiary_id"])
    )).scalar_one()
    assert beneficiary.email == "traveller@example.com"
    assert "customer.esim.local" not in beneficiary.email
    assert not beneficiary.username.startswith("user_"), "fell back to a placeholder username"
    assert beneficiary.phone == "+8801711223344"


async def test_the_customer_can_sign_in_with_their_phone_number(
    client, db_session, promote_role, captured_account_emails
):
    merchant = await _merchant(client, db_session, promote_role, "phoneshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="phoneuser@example.com", phone="01711-223355")

    # Punctuation is stripped: the merchant types it however they like.
    res = await client.post("/api/v1/auth/login",
                            json={"email": "phoneuser@example.com", "password": "01711223355"})
    assert res.status_code == 200, res.text
    assert res.json()["must_change_password"] is True


async def test_an_existing_customer_gets_the_esim_on_their_own_account(
    client, db_session, promote_role, captured_account_emails
):
    """A repeat customer must not end up with a second account they do not
    know about - the eSIM belongs on the one they already sign in to."""
    customer = await register_and_login(client, "repeatcustomer")
    merchant = await _merchant(client, db_session, promote_role, "repeatshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    before = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    res = await _sell_to(client, merchant, product, email=customer["email"].upper(), phone="019000000")
    assert res.status_code == 202, res.text

    assert res.json()["beneficiary_id"] == customer["user_id"], "matched case-sensitively"
    after = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert after == before, "created a duplicate account for an existing customer"
    assert captured_account_emails == [], "emailed credentials for an account that already existed"


async def test_the_customer_is_emailed_their_credentials(
    client, db_session, promote_role, captured_account_emails
):
    merchant = await _merchant(client, db_session, promote_role, "mailshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="mailme@example.com", phone="+8801799887766")

    assert len(captured_account_emails) == 1
    mail = captured_account_emails[0]
    assert mail["to"] == "mailme@example.com"
    assert mail["password"] == "8801799887766"
    assert mail["password_is_phone"] is True
    # Who opened the account, so it does not read as phishing.
    assert merchant["username"] in mail["created_by"]


async def test_without_a_phone_a_random_password_is_generated(
    client, db_session, promote_role, captured_account_emails
):
    """A three-digit "password" would be worse than making them read an
    email, so a missing or unusable phone falls back to a random one."""
    merchant = await _merchant(client, db_session, promote_role, "nophoneshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="nophone@example.com")

    mail = captured_account_emails[0]
    assert mail["password_is_phone"] is False
    assert len(mail["password"]) == 8


async def test_the_order_records_who_bought_it_and_who_it_is_for(
    client, db_session, promote_role, captured_account_emails
):
    merchant = await _merchant(client, db_session, promote_role, "recordshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    res = await _sell_to(client, merchant, product, email="forwhom@example.com", phone="01712345678")

    order = (await db_session.execute(
        select(Order).where(Order.id == res.json()["id"])
    )).scalar_one()
    assert order.buyer_id == merchant["user_id"]
    assert order.beneficiary_id != merchant["user_id"]
    assert order.is_reseller_order is True


# --- the provisional password is not a licence to spend ---

async def test_a_provisional_password_cannot_buy_or_withdraw(
    client, db_session, promote_role, captured_account_emails
):
    """Forcing the change in the browser alone would be theatre: the phone
    number is often public, so the API has to refuse too."""
    merchant = await _merchant(client, db_session, promote_role, "lockshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="locked@example.com", phone=PHONE_LOCKED)

    login = await client.post("/api/v1/auth/login",
                              json={"email": "locked@example.com", "password": PHONE_LOCKED})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    buy = await client.post("/api/v1/orders/checkout",
                            json={"product_id": product.id, "payment_method": "WALLET"},
                            headers=headers)
    assert buy.status_code == 403
    assert "password" in buy.json()["detail"].lower()


async def test_they_can_still_see_what_was_bought_for_them(
    client, db_session, promote_role, captured_account_emails
):
    """The lock is on moving money, not on looking: the whole point of the
    account is that the customer can see the eSIM they were given."""
    merchant = await _merchant(client, db_session, promote_role, "viewshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="viewer@example.com", phone=PHONE_VIEWER)

    login = await client.post("/api/v1/auth/login",
                              json={"email": "viewer@example.com", "password": PHONE_VIEWER})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/v1/orders/my-esims", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200


async def test_changing_the_password_unlocks_the_account(
    client, db_session, promote_role, captured_account_emails
):
    merchant = await _merchant(client, db_session, promote_role, "unlockshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="unlock@example.com", phone=PHONE_UNLOCK)

    login = await client.post("/api/v1/auth/login",
                              json={"email": "unlock@example.com", "password": PHONE_UNLOCK})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.post("/api/v1/auth/change-password", headers=headers,
                                json={"current_password": PHONE_UNLOCK, "new_password": CHOSEN_PW})
    assert changed.status_code == 200, changed.text

    again = await client.post("/api/v1/auth/login",
                              json={"email": "unlock@example.com", "password": CHOSEN_PW})
    assert again.json()["must_change_password"] is False

    headers2 = {"Authorization": f"Bearer {again.json()['access_token']}"}
    buy = await client.post("/api/v1/orders/checkout",
                            json={"product_id": product.id, "payment_method": "WALLET"},
                            headers=headers2)
    # Refused for having no money, not for the password - the lock is gone.
    assert buy.status_code != 403


async def test_the_wrong_current_password_is_refused(
    client, db_session, promote_role, captured_account_emails
):
    merchant = await _merchant(client, db_session, promote_role, "wrongpwshop")
    product = await create_test_product(db_session, price=Decimal("10.0000"))
    await _sell_to(client, merchant, product, email="wrongpw@example.com", phone=PHONE_WRONGPW)

    login = await client.post("/api/v1/auth/login",
                              json={"email": "wrongpw@example.com", "password": PHONE_WRONGPW})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    res = await client.post("/api/v1/auth/change-password", headers=headers,
                            json={"current_password": WRONG_PW, "new_password": CHOSEN_PW})
    assert res.status_code == 400
