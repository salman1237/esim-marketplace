import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8ffffff3f0005fe02fea739666e0000000049454e44ae426082"
)


async def test_kyc_submit_and_self_status(client):
    user = await register_and_login(client, "kycuser")

    before = await client.get("/api/v1/kyc/me", headers=user["headers"])
    assert before.json() == {"submitted": False, "status": None}

    submit = await client.post(
        "/api/v1/kyc/submit",
        data={"nid_number": "1234567890"},
        files={"document_front": ("front.png", _TINY_PNG, "image/png")},
        headers=user["headers"],
    )
    assert submit.status_code == 200, submit.text

    after = await client.get("/api/v1/kyc/me", headers=user["headers"])
    assert after.json()["submitted"] is True
    assert after.json()["status"] == "PENDING"

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["is_kyc_verified"] is False


async def test_kyc_queue_and_approve_sets_verified(client, promote_role):
    user = await register_and_login(client, "kycapprove")
    await client.post(
        "/api/v1/kyc/submit",
        data={"nid_number": "9988776655"},
        files={
            "document_front": ("front.png", _TINY_PNG, "image/png"),
            "document_back": ("back.png", _TINY_PNG, "image/png"),
        },
        headers=user["headers"],
    )

    admin = await register_and_login(client, "kycreviewer")
    await promote_role(admin["user_id"], "ADMIN")

    queue = await client.get("/api/v1/admin/kyc/queue", headers=admin["headers"])
    assert queue.status_code == 200
    entry = next(k for k in queue.json() if k["user_id"] == user["user_id"])
    assert entry["nid_number"] == "9988776655"
    assert entry["has_back_document"] is True
    assert entry["status"] == "PENDING"

    front_doc = await client.get(f"/api/v1/admin/kyc/{entry['id']}/document/front", headers=admin["headers"])
    assert front_doc.status_code == 200
    assert front_doc.content == _TINY_PNG

    approve = await client.post(f"/api/v1/admin/kyc/{entry['id']}/approve", headers=admin["headers"])
    assert approve.status_code == 200, approve.text

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["is_kyc_verified"] is True

    # Double-approval is rejected by the status guard
    approve_again = await client.post(f"/api/v1/admin/kyc/{entry['id']}/approve", headers=admin["headers"])
    assert approve_again.status_code == 400


async def test_kyc_reject_then_resubmit(client, promote_role):
    user = await register_and_login(client, "kycreject")
    submit1 = await client.post(
        "/api/v1/kyc/submit",
        data={"nid_number": "1111111111"},
        files={"document_front": ("front.png", _TINY_PNG, "image/png")},
        headers=user["headers"],
    )
    assert submit1.status_code == 200

    admin = await register_and_login(client, "kycrejector")
    await promote_role(admin["user_id"], "ADMIN")
    queue = await client.get("/api/v1/admin/kyc/queue", headers=admin["headers"])
    entry = next(k for k in queue.json() if k["user_id"] == user["user_id"])

    rejected = await client.post(
        f"/api/v1/admin/kyc/{entry['id']}/reject?reason=Blurry+photo", headers=admin["headers"]
    )
    assert rejected.status_code == 200

    status = await client.get("/api/v1/kyc/me", headers=user["headers"])
    assert status.json()["status"] == "REJECTED"
    assert status.json()["rejection_reason"] == "Blurry photo"

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.json()["is_kyc_verified"] is False

    # Resubmission clears the rejection and goes back to PENDING under the
    # same submission (one row per user - a unique constraint on user_id).
    submit2 = await client.post(
        "/api/v1/kyc/submit",
        data={"nid_number": "1111111111"},
        files={"document_front": ("front2.png", _TINY_PNG, "image/png")},
        headers=user["headers"],
    )
    assert submit2.status_code == 200
    status2 = await client.get("/api/v1/kyc/me", headers=user["headers"])
    assert status2.json()["status"] == "PENDING"
    assert status2.json()["rejection_reason"] is None


async def test_kyc_endpoints_require_admin(client):
    user = await register_and_login(client, "kycplainuser")
    res = await client.get("/api/v1/admin/kyc/queue", headers=user["headers"])
    assert res.status_code == 403
