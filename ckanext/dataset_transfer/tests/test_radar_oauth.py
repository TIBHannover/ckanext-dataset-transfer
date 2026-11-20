import datetime
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "dataset_transfer"),
    pytest.mark.usefixtures("with_plugins"),
]


class FakeResponse(object):
    def __init__(self, status_code=200, payload=None, url="https://radar.example.test"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)
        self.url = url

    def json(self):
        return self._payload


class FakeOAuthSession(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected OAuth request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def dataset_transfer_migrated_db(clean_db):
    import ckan.cli.db as db
    import ckan.plugins as plugins

    if not plugins.plugin_loaded("dataset_transfer"):
        plugins.load("dataset_transfer")
    db._run_migrations("dataset_transfer", None, True)


@pytest.fixture
def radar_oauth_config(monkeypatch):
    import ckan.plugins.toolkit as toolkit
    from cryptography.fernet import Fernet

    values = {
        "ckanext.dataset_transfer.radar.oauth_environment": "test",
        "ckanext.dataset_transfer.radar.oauth_authorize_url": (
            "https://test.radar-service.eu/radar-backend/oauth/authorize"
        ),
        "ckanext.dataset_transfer.radar.oauth_token_url": (
            "https://test.radar-service.eu/radar-backend/oauth/token"
        ),
        "ckanext.dataset_transfer.radar.oauth_refresh_url": (
            "https://test.radar-service.eu/radar/api/tokens/refresh"
        ),
        "ckanext.dataset_transfer.radar.oauth_callback_url": (
            "https://ckan.example.test/dataset_transfer/radar/callback"
        ),
        "ckanext.dataset_transfer.radar.oauth_refresh_mode": "radar_api",
        "ckanext.dataset_transfer.radar.oauth_token_encryption_key": (
            Fernet.generate_key().decode("ascii")
        ),
        "ckanext.dataset_transfer.radar.oauth_state_ttl": "600",
        "ckanext.dataset_transfer.radar.oauth_timeout": "5",
        "ckanext.dataset_transfer.radar.oauth_refresh_margin": "300",
        "ckanext.dataset_transfer.radar.client_id": "oauth-client",
        "ckanext.dataset_transfer.radar.client_secret": "oauth-secret",
        "ckanext.dataset_transfer.radar.context_url": (
            "https://test.radar-service.eu/radar"
        ),
        "ckanext.dataset_transfer.radar.workspace_id": "workspace-id",
        "ckanext.dataset_transfer.radar.responsible_email": "data@example.test",
    }
    for key, value in values.items():
        monkeypatch.setitem(toolkit.config, key, value)
    return values


def _auth_headers(user):
    return {"Authorization": user["token"]}


def _begin_oauth(app, user, dataset):
    client = app.test_client()
    response = client.get(
        "/dataset_transfer/radar/login?dataset_name={}".format(dataset["name"]),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    query = parse_qs(urlparse(response.location).query)
    return response, query, client


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_authenticated_user_starts_authorization_with_server_side_state(
    app, radar_oauth_config
):
    import ckan.tests.factories as factories
    from ckan.model import meta
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthState

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    response, query, _ = _begin_oauth(app, user, dataset)

    assert response.location.startswith(radar_oauth_config[
        "ckanext.dataset_transfer.radar.oauth_authorize_url"
    ])
    assert query["client_id"] == ["oauth-client"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [radar_oauth_config[
        "ckanext.dataset_transfer.radar.oauth_callback_url"
    ]]
    assert len(query["state"][0]) >= 40
    flow = meta.Session.query(RadarOAuthState).one()
    assert flow.ckan_user_id == user["id"]
    assert flow.dataset_name == dataset["name"]
    assert flow.state_hash != query["state"][0]


def test_unauthenticated_user_cannot_start_oauth(app, radar_oauth_config):
    response = app.get(
        "/dataset_transfer/radar/login?dataset_name=anything",
        expect_errors=True,
    )
    assert response.status_code == 401


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_pkce_s256_is_opt_in(app, monkeypatch, radar_oauth_config):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.oauth_pkce_enabled",
        "true",
    )
    _, query, _ = _begin_oauth(
        app, factories.SysadminWithToken(), factories.Dataset()
    )
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_callback_exchanges_code_and_returns_to_dataset(
    app, monkeypatch, radar_oauth_config
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services import radar_oauth

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset)
    calls = []

    def exchange(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {
            "access_token": "oliver-access-token",
            "refresh_token": "oliver-refresh-token",
            "expires_in": 3600,
        })

    monkeypatch.setattr(radar_oauth.requests, "post", exchange)
    response = client.get(
        "/dataset_transfer/radar/callback?code=one-time-code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )

    assert "/dataset_transfer/publish_page/{}".format(dataset["name"]) in response.location
    assert "publish_target=radar" in response.location
    assert calls[0][0] == radar_oauth_config[
        "ckanext.dataset_transfer.radar.oauth_token_url"
    ]
    assert calls[0][1]["auth"] == ("oauth-client", "oauth-secret")
    assert calls[0][1]["data"]["redirect_uri"] == radar_oauth_config[
        "ckanext.dataset_transfer.radar.oauth_callback_url"
    ]
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    assert record.access_token_encrypted != "oliver-access-token"
    assert record.refresh_token_encrypted != "oliver-refresh-token"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_callback_rejects_invalid_state(app, radar_oauth_config):
    import ckan.tests.factories as factories

    user = factories.SysadminWithToken()
    response = app.get(
        "/dataset_transfer/radar/callback?code=code&state=invalid",
        headers=_auth_headers(user),
        expect_errors=True,
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_callback_state_cannot_be_used_by_another_ckan_user(
    app, radar_oauth_config
):
    import ckan.tests.factories as factories

    owner = factories.SysadminWithToken()
    attacker = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, owner, dataset)
    response = client.get(
        "/dataset_transfer/radar/callback?code=code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(attacker),
        expect_errors=True,
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_callback_rejects_expired_state(app, radar_oauth_config):
    import ckan.tests.factories as factories
    from ckan.model import meta
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthState

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset)
    flow = meta.Session.query(RadarOAuthState).one()
    flow.created_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    flow.save()
    response = client.get(
        "/dataset_transfer/radar/callback?code=code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(user),
        expect_errors=True,
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
@pytest.mark.parametrize("callback_query", ["", "error=access_denied"])
def test_callback_handles_missing_code_and_provider_denial(
    app, radar_oauth_config, callback_query
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset)
    suffix = "&{}".format(callback_query) if callback_query else ""
    response = client.get(
        "/dataset_transfer/radar/callback?state={}{}".format(
            query["state"][0], suffix
        ),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    assert dataset["name"] in response.location
    assert not RadarOAuthToken.get_by_user_environment(user["id"], "test")


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_token_exchange_failure_consumes_state_without_exposing_tokens(
    app, monkeypatch, radar_oauth_config
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services import radar_oauth

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset)
    monkeypatch.setattr(
        radar_oauth.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(401, {"access_token": "must-not-leak"}),
    )
    response = client.get(
        "/dataset_transfer/radar/callback?code=sensitive-code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    response_text = response.get_data(as_text=True)
    assert "must-not-leak" not in response_text
    assert "sensitive-code" not in response_text


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_oauth_return_destination_cannot_be_overridden(
    app, monkeypatch, radar_oauth_config
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services import radar_oauth

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    client = app.test_client()
    response = client.get(
        "/dataset_transfer/radar/login?dataset_name={}&next=https://evil.example".format(
            dataset["name"]
        ),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    state = parse_qs(urlparse(response.location).query)["state"][0]
    monkeypatch.setattr(
        radar_oauth.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {
            "access_token": "access", "refresh_token": "refresh", "expires_in": 3600
        }),
    )
    callback = client.get(
        "/dataset_transfer/radar/callback?code=code&state={}".format(state),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    assert "evil.example" not in callback.location
    assert dataset["name"] in callback.location


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_tokens_are_isolated_by_ckan_user_and_disconnect_is_scoped(
    radar_oauth_config,
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    oliver = factories.User()
    second_user = factories.User()
    service = RadarOAuthService()
    service._save_token_response(oliver["id"], {
        "access_token": "oliver-token", "refresh_token": "oliver-refresh", "expires_in": 3600
    })
    service._save_token_response(second_user["id"], {
        "access_token": "second-token", "refresh_token": "second-refresh", "expires_in": 3600
    })
    assert service.get_valid_access_token(oliver["id"]) == "oliver-token"
    assert service.get_valid_access_token(second_user["id"]) == "second-token"
    service.disconnect(oliver["id"])
    assert service.connection_status(oliver["id"], False)["connected"] is False
    assert service.get_valid_access_token(second_user["id"]) == "second-token"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_valid_token_does_not_refresh(radar_oauth_config):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.User()
    fake_http = FakeOAuthSession([])
    service = RadarOAuthService(request_session=fake_http)
    service._save_token_response(user["id"], {
        "access_token": "valid-token", "refresh_token": "refresh", "expires_in": 3600
    })
    assert service.get_valid_access_token(user["id"]) == "valid-token"
    assert fake_http.calls == []


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_expired_token_refreshes_and_rotates_refresh_token(radar_oauth_config):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.User()
    fake_http = FakeOAuthSession([FakeResponse(200, {
        "access_token": "new-access",
        "refresh_token": "rotated-refresh",
        "expires_in": 7200,
    })])
    service = RadarOAuthService(request_session=fake_http)
    service._save_token_response(user["id"], {
        "access_token": "old-access", "refresh_token": "old-refresh", "expires_in": 1
    })
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    record.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    record.save()
    assert service.get_valid_access_token(user["id"]) == "new-access"
    assert fake_http.calls[0][1]["json"]["refreshToken"] == "old-refresh"
    assert service._decrypt_required(record.refresh_token_encrypted) == "rotated-refresh"
    assert service.get_valid_access_token(user["id"]) == "new-access"
    assert len(fake_http.calls) == 1


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_refresh_without_rotation_preserves_existing_refresh_token(
    radar_oauth_config,
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.User()
    service = RadarOAuthService(request_session=FakeOAuthSession([
        FakeResponse(200, {"access_token": "new-access", "expires_in": 3600})
    ]))
    service._save_token_response(user["id"], {
        "access_token": "old", "refresh_token": "keep-me", "expires_in": 1
    })
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    record.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    assert service.get_valid_access_token(user["id"]) == "new-access"
    assert service._decrypt_required(record.refresh_token_encrypted) == "keep-me"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_rejected_refresh_requires_reauthentication(radar_oauth_config):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthService,
        RadarReauthenticationRequired,
    )

    user = factories.User()
    service = RadarOAuthService(
        request_session=FakeOAuthSession([FakeResponse(401, {})])
    )
    service._save_token_response(user["id"], {
        "access_token": "old", "refresh_token": "revoked", "expires_in": 1
    })
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    record.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    with pytest.raises(RadarReauthenticationRequired):
        service.get_valid_access_token(user["id"])
    assert record.requires_reauthentication is True


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
@pytest.mark.parametrize("failure", [FakeResponse(429, {}), "timeout"])
def test_temporary_refresh_failure_does_not_revoke_connection(
    radar_oauth_config, failure
):
    import requests
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthService,
        RadarOAuthTemporaryError,
    )

    user = factories.User()
    failure = requests.Timeout("timeout") if failure == "timeout" else failure
    service = RadarOAuthService(request_session=FakeOAuthSession([failure]))
    service._save_token_response(user["id"], {
        "access_token": "old", "refresh_token": "refresh", "expires_in": 1
    })
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    record.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    with pytest.raises(RadarOAuthTemporaryError):
        service.get_valid_access_token(user["id"])
    assert record.requires_reauthentication is False


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_refresh_acquires_database_row_lock(monkeypatch, radar_oauth_config):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.models.radar_oauth import RadarOAuthToken
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.User()
    service = RadarOAuthService(request_session=FakeOAuthSession([
        FakeResponse(200, {
            "access_token": "new", "refresh_token": "new-refresh", "expires_in": 3600
        })
    ]))
    service._save_token_response(user["id"], {
        "access_token": "old", "refresh_token": "old-refresh", "expires_in": 1
    })
    record = RadarOAuthToken.get_by_user_environment(user["id"], "test")
    record.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    original = RadarOAuthToken.get_by_user_environment.__func__
    lock_requests = []

    def get_record(cls, user_id, environment, autoflush=True, for_update=False):
        lock_requests.append(for_update)
        return original(cls, user_id, environment, autoflush, for_update)

    monkeypatch.setattr(
        RadarOAuthToken, "get_by_user_environment", classmethod(get_record)
    )
    assert service.get_valid_access_token(user["id"]) == "new"
    assert lock_requests[0] is True


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_missing_connection_requires_authentication(radar_oauth_config):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthService,
        RadarReauthenticationRequired,
    )

    with pytest.raises(RadarReauthenticationRequired):
        RadarOAuthService().get_valid_access_token(factories.User()["id"])


def test_environment_mismatch_is_rejected(radar_oauth_config):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthConfigError,
        RadarOAuthService,
    )

    config = dict(toolkit.config)
    config.update(radar_oauth_config)
    config["ckanext.dataset_transfer.radar.context_url"] = (
        "https://www.radar-service.eu/radar"
    )
    with pytest.raises(RadarOAuthConfigError):
        RadarOAuthService(config=config)


def test_radar_publisher_has_no_shared_credential_fallback(radar_oauth_config):
    from ckanext.dataset_transfer.services.radar import RadarConfigError, RadarPublisher

    config = dict(radar_oauth_config)
    config["ckanext.dataset_transfer.radar.access_token"] = "shared-token"
    with pytest.raises(RadarConfigError):
        RadarPublisher(config=config)


def test_workspace_permission_error_is_clear(radar_oauth_config):
    from ckanext.dataset_transfer.services.radar import RadarPublishError, RadarPublisher

    publisher = RadarPublisher(
        config=radar_oauth_config,
        access_token="user-token",
        request_session=FakeOAuthSession([FakeResponse(403, {})]),
    )
    with pytest.raises(RadarPublishError, match="workspace administrator"):
        publisher._create_dataset({"id": "dataset", "title": "Dataset"})


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_page_shows_connection_state_without_exposing_token(
    app, radar_oauth_config
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    disconnected = app.get(
        toolkit.url_for("dataset_transfer.publish_page", dataset_name=dataset["name"]),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    assert "Connect your RADAR4Ing account" in disconnected
    assert "Connect to RADAR4Ing" in disconnected
    assert 'data-radar-connected="false"' in disconnected

    RadarOAuthService()._save_token_response(user["id"], {
        "access_token": "never-render-access",
        "refresh_token": "never-render-refresh",
        "expires_in": 3600,
    })
    connected = app.get(
        toolkit.url_for(
            "dataset_transfer.publish_page",
            dataset_name=dataset["name"],
            publish_target="radar",
        ),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    assert "Connected to RADAR4Ing" in connected
    assert 'data-radar-connected="true"' in connected
    assert '<option value="radar" selected>' in connected
    assert "never-render-access" not in connected
    assert "never-render-refresh" not in connected


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_disconnect_requires_csrf_and_affects_only_current_user(
    app, radar_oauth_config
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.SysadminWithToken()
    other = factories.User()
    dataset = factories.Dataset()
    service = RadarOAuthService()
    for current_user, token in ((user, "current"), (other, "other")):
        service._save_token_response(current_user["id"], {
            "access_token": token,
            "refresh_token": token + "-refresh",
            "expires_in": 3600,
        })
    client = app.test_client()
    page = client.get(
        toolkit.url_for("dataset_transfer.publish_page", dataset_name=dataset["name"]),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    csrf = re.search(r'name="_csrf_token" value="([^"]+)"', page)
    assert csrf, page

    rejected = client.post(
        "/dataset_transfer/radar/disconnect",
        data={"dataset_name": dataset["name"]},
        headers=_auth_headers(user),
        expect_errors=True,
    )
    assert rejected.status_code == 400

    response = client.post(
        "/dataset_transfer/radar/disconnect",
        data={
            "dataset_name": dataset["name"],
            "_csrf_token": csrf.group(1),
        },
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    assert dataset["name"] in response.location
    assert service.connection_status(user["id"], False)["connected"] is False
    assert service.get_valid_access_token(other["id"]) == "other"


def test_frontend_gates_radar_review_without_changing_metadata_navigation():
    source = (
        Path(__file__).parents[1] / "public" / "transfer.js"
    ).read_text(encoding="utf-8")
    assert "data('radar-connected') !== true" in source
    assert "let radarSectionOrder = ['dataset', 'creators', 'classification', 'rights', 'funding'];" in source
    assert "formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));" in source
    assert "radar.user_password" not in source
    assert "radar.user_name" not in source
