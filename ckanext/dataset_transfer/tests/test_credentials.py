import re

import pytest


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "dataset_transfer"),
]


@pytest.fixture(scope="module", autouse=True)
def restore_extension_logger_after_module():
    import logging
    yield
    logging.getLogger("ckanext.dataset_transfer.libs.helper").disabled = False


@pytest.fixture
def credential_db(clean_db, app):
    import ckan.cli.db as db
    db._run_migrations("dataset_transfer", None, True)


def _headers(user):
    return {"Authorization": user["token"]}


def _csrf(html):
    match = re.search(
        r'<input[^>]+name="([^"]*csrf[^"]*)"[^>]+value="([^"]+)"', html
    )
    assert match, "CSRF input was not rendered"
    return {match.group(1): match.group(2)}


@pytest.mark.usefixtures("credential_db")
def test_unauthenticated_user_cannot_access_credentials(app):
    response = app.get("/dataset_transfer/credentials", status=403)
    assert b"Authentication required" in response.data


@pytest.mark.usefixtures("credential_db")
def test_credentials_page_masks_existing_token_and_never_renders_full_value(app):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.credentials import CredentialService

    user = factories.UserWithToken()
    full_token = "destination-secret-token-a8F2"
    user_obj = CredentialService.user_from_action_context({"user": user["name"]})
    CredentialService.save_for_user(user_obj, full_token)

    response = app.get("/dataset_transfer/credentials", headers=_headers(user))
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "a8F2" in html
    assert full_token not in html
    assert "Configured" in html
    assert 'type="password"' in html


@pytest.mark.usefixtures("credential_db")
def test_missing_token_is_reported_without_a_secret_field_value(app):
    import ckan.tests.factories as factories

    user = factories.UserWithToken()
    html = app.get("/dataset_transfer/credentials", headers=_headers(user)).get_data(as_text=True)
    assert "Not configured" in html
    assert "Missing" in html
    assert 'value=' not in re.search(r'<input[^>]+name="luh_api_token"[^>]*>', html).group(0)


@pytest.mark.usefixtures("credential_db")
def test_add_replace_and_remove_token(app):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken
    from ckanext.dataset_transfer.services.credentials import CredentialService

    user = factories.UserWithToken()
    user_obj = CredentialService.user_from_action_context({"user": user["name"]})
    client = app.test_client()

    page = client.get("/dataset_transfer/credentials", headers=_headers(user))
    data = _csrf(page.get_data(as_text=True)); data["luh_api_token"] = "first-secret"
    client.post("/dataset_transfer/credentials/save", data=data, headers=_headers(user))
    assert PublishApiToken.get_by_user(user_obj.id).api_token == "first-secret"

    # Preserve compatibility with legacy databases while collapsing any
    # historical duplicate rows during replacement.
    PublishApiToken(
        api_token="legacy-duplicate",
        user_id=user_obj.id,
        target_ckan="https://example.invalid/",
    ).save()

    page = client.get("/dataset_transfer/credentials", headers=_headers(user))
    data = _csrf(page.get_data(as_text=True)); data["luh_api_token"] = "replacement-secret"
    client.post("/dataset_transfer/credentials/save", data=data, headers=_headers(user))
    assert PublishApiToken.get_by_user(user_obj.id).api_token == "replacement-secret"
    assert len(PublishApiToken.get_all_by_user(user_obj.id)) == 1

    page = client.get("/dataset_transfer/credentials", headers=_headers(user))
    client.post("/dataset_transfer/credentials/remove", data=_csrf(page.get_data(as_text=True)), headers=_headers(user))
    assert not PublishApiToken.get_by_user(user_obj.id)


@pytest.mark.usefixtures("credential_db")
def test_empty_token_is_rejected_and_existing_token_is_preserved(app):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.credentials import CredentialService

    user = factories.UserWithToken()
    user_obj = CredentialService.user_from_action_context({"user": user["name"]})
    CredentialService.save_for_user(user_obj, "keep-this-secret")
    client = app.test_client()
    page = client.get("/dataset_transfer/credentials", headers=_headers(user))
    data = _csrf(page.get_data(as_text=True)); data["luh_api_token"] = "   "
    response = client.post("/dataset_transfer/credentials/save", data=data, headers=_headers(user), follow_redirects=True)
    assert CredentialService.record_for_user(user_obj).api_token == "keep-this-secret"
    assert b"non-empty LUH API token" in response.data


@pytest.mark.usefixtures("credential_db")
def test_browser_mutations_require_csrf(app):
    import ckan.tests.factories as factories
    user = factories.UserWithToken()
    app.post("/dataset_transfer/credentials/save", params={"luh_api_token": "secret"}, headers=_headers(user), status=400)


@pytest.mark.usefixtures("credential_db")
def test_users_only_see_their_own_external_token_and_navigation(app):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.credentials import CredentialService

    owner = factories.UserWithToken()
    other = factories.UserWithToken()
    owner_obj = CredentialService.user_from_action_context({"user": owner["name"]})
    CredentialService.save_for_user(owner_obj, "owner-only-secret-7788")

    own_html = app.get("/user/{}".format(other["name"]), headers=_headers(other)).get_data(as_text=True)
    foreign_html = app.get("/user/{}".format(owner["name"]), headers=_headers(other)).get_data(as_text=True)
    assert "External API Tokens" in own_html
    assert "/dataset_transfer/credentials" in own_html
    assert "External API Tokens" not in foreign_html
    assert "owner-only-secret-7788" not in foreign_html


@pytest.mark.usefixtures("credential_db")
def test_credentials_navigation_is_active_and_core_tabs_remain(app):
    import ckan.tests.factories as factories
    user = factories.UserWithToken()
    html = app.get("/dataset_transfer/credentials", headers=_headers(user)).get_data(as_text=True)
    assert re.search(r'class="[^"]*active[^"]*"[^>]*>\s*<a[^>]+dataset_transfer/credentials', html)
    assert "API Tokens" in html
    assert "/user/{}/api-tokens".format(user["name"]) in html


@pytest.mark.usefixtures("credential_db")
def test_action_api_uses_stored_token_for_authenticated_api_user(app, monkeypatch):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.credentials import CredentialService
    from ckanext.dataset_transfer.services.publish import PublishService

    user = factories.SysadminWithToken()
    package = factories.Dataset()
    user_obj = CredentialService.user_from_action_context({"user": user["name"]})
    CredentialService.save_for_user(user_obj, "stored-luh-destination-token")
    monkeypatch.setitem(toolkit.config, "ckanext.dataset_transfer.luh.enabled", True)
    captured = {}

    def fake_publish(dataset, target, reviewed_metadata, destination_token):
        captured["token"] = destination_token
        return {"dataset_id": dataset["id"], "target": target, "status": "transferred"}

    monkeypatch.setattr(PublishService, "publish", fake_publish)
    response = app.post("/api/3/action/dataset_transfer_publish", json={
        "dataset_id": package["id"], "target": "luh",
        "terms_accepted": True, "rights_confirmed": True,
    }, headers=_headers(user))
    assert response.json["success"] is True
    assert captured["token"] == "stored-luh-destination-token"
    assert "stored-luh-destination-token" not in response.get_data(as_text=True)


@pytest.mark.usefixtures("credential_db")
def test_connection_check_requires_create_dataset_permission(app, monkeypatch):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers.base import BaseController
    from ckanext.dataset_transfer.services.credentials import CredentialService

    user = factories.UserWithToken()
    user_obj = CredentialService.user_from_action_context({"user": user["name"]})
    CredentialService.save_for_user(user_obj, "connection-test-secret")
    monkeypatch.setitem(toolkit.config, "ckanext.dataset_transfer.target_organization", "target-org")

    def fake_remote(method, action, **kwargs):
        assert kwargs["headers"]["Authorization"] == "connection-test-secret"
        if action == "organization_show":
            return {"result": {"id": "target-id", "name": "target-org", "title": "Target Org"}}
        assert kwargs["params"] == {"permission": "create_dataset"}
        return {"result": []}

    monkeypatch.setattr(BaseController, "_remote_json", fake_remote)
    client = app.test_client()
    page = client.get("/dataset_transfer/credentials", headers=_headers(user))
    response = client.post(
        "/dataset_transfer/credentials/test",
        data=_csrf(page.get_data(as_text=True)),
        headers=_headers(user),
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "cannot create datasets" in html
    assert "connection-test-secret" not in html
