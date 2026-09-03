import pytest
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def test_get_english_translations_returns_base_strings(client):
    res = await client.get("/api/v1/settings/translations/en")
    assert res.status_code == 200
    data = res.json()
    assert data["language_code"] == "en"
    assert data["namespaces"]["common"]["site_name"]


async def test_missing_language_falls_back_to_english(client):
    """Regression test for the plan's 'zero-break fallback' requirement: a
    language with no translations at all still returns the full English
    string set rather than gaps."""
    res = await client.get("/api/v1/settings/translations/xx")
    assert res.status_code == 200
    data = res.json()
    assert data["namespaces"]["common"]["site_name"] == "eSIM Global"


async def test_super_admin_can_create_language_and_seed_it(client, promote_role):
    sa = await register_and_login(client, "translang")
    await promote_role(sa["user_id"], "SUPER_ADMIN")

    create = await client.post(
        "/api/v1/admin/languages",
        json={"code": "ko", "name": "Korean", "native_name": "한국어", "is_rtl": False, "seed_from_english": True},
        headers=sa["headers"],
    )
    assert create.status_code == 200, create.text
    assert create.json()["seeded_keys"] > 0

    langs = await client.get("/api/v1/settings/languages")
    assert any(l["code"] == "ko" for l in langs.json())

    translations = await client.get("/api/v1/settings/translations/ko")
    assert translations.json()["namespaces"]["common"]["site_name"] == "eSIM Global"  # seeded placeholder = English text


async def test_super_admin_can_edit_a_translation_string(client, promote_role):
    sa = await register_and_login(client, "transedit")
    await promote_role(sa["user_id"], "SUPER_ADMIN")

    await client.post(
        "/api/v1/admin/languages",
        json={"code": "fr2", "name": "French Test", "native_name": "Français", "seed_from_english": True},
        headers=sa["headers"],
    )
    upsert = await client.put(
        "/api/v1/admin/translations",
        json={"language_code": "fr2", "namespace": "common", "key": "site_name", "value": "eSIM Mondial"},
        headers=sa["headers"],
    )
    assert upsert.status_code == 200, upsert.text

    translations = await client.get("/api/v1/settings/translations/fr2")
    assert translations.json()["namespaces"]["common"]["site_name"] == "eSIM Mondial"
    # untouched keys still fall back to the seeded/English value
    assert translations.json()["namespaces"]["common"]["login"] == "Sign In"


async def test_non_super_admin_cannot_manage_translations(client, promote_role):
    admin = await register_and_login(client, "transadmin")
    await promote_role(admin["user_id"], "ADMIN")

    res = await client.post(
        "/api/v1/admin/languages",
        json={"code": "vi", "name": "Vietnamese", "native_name": "Tiếng Việt"},
        headers=admin["headers"],
    )
    assert res.status_code == 403
