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
        "ckanext.dataset_transfer.radar.oauth_attempt_ttl": "3600",
        "ckanext.dataset_transfer.radar.oauth_active_attempt_ttl": "7200",
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


@pytest.fixture
def radar_redis(radar_oauth_config):
    import os
    import redis
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    redis_url = toolkit.config.get("ckan.redis.url") or os.environ.get(
        "CKAN_REDIS_URL"
    )
    client = redis.Redis.from_url(redis_url, decode_responses=False)
    keys = list(client.scan_iter(RadarOAuthService.KEY_PREFIX + ":*"))
    if keys:
        client.delete(*keys)
    yield client
    keys = list(client.scan_iter(RadarOAuthService.KEY_PREFIX + ":*"))
    if keys:
        client.delete(*keys)


def _service(radar_redis, responses=None, **kwargs):
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    return RadarOAuthService(
        redis_client=radar_redis,
        request_session=FakeOAuthSession(responses or []),
        **kwargs
    )


def _store_attempt(
    service, user="user-a", dataset="dataset-a", binding="binding-a",
    attempt="attempt-a", access="access-a", refresh="refresh-a",
    expires_in=3600
):
    service._save_token_response(
        user_id=user,
        dataset_id=dataset,
        dataset_name=dataset,
        session_binding=binding,
        attempt_id=attempt,
        token_data={
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": expires_in,
        },
    )
    return attempt


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
def test_login_stores_encrypted_state_in_redis(
    app, radar_oauth_config, radar_redis
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    response, query, _ = _begin_oauth(app, user, dataset)
    assert response.location.startswith(
        radar_oauth_config["ckanext.dataset_transfer.radar.oauth_authorize_url"]
    )
    assert query["client_id"] == ["oauth-client"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [
        radar_oauth_config["ckanext.dataset_transfer.radar.oauth_callback_url"]
    ]
    service = _service(radar_redis)
    state_key = service._state_key(service._hash(query["state"][0]))
    stored = radar_redis.get(state_key)
    assert stored
    assert user["id"].encode("utf-8") not in stored
    assert dataset["id"].encode("utf-8") not in stored
    assert 0 < radar_redis.ttl(state_key) <= 600


def test_unauthenticated_user_cannot_start_oauth(app, radar_oauth_config):
    response = app.get(
        "/dataset_transfer/radar/login?dataset_name=anything",
        expect_errors=True,
    )
    assert response.status_code == 401


def test_state_is_atomic_single_use_and_tokens_are_temporary(
    radar_oauth_config, radar_redis
):
    service = _service(radar_redis, [FakeResponse(200, {
        "access_token": "access-secret",
        "refresh_token": "refresh-secret",
        "expires_in": 3600,
    })])
    url, binding, _ = service.authorization_url(
        "user-a", "dataset-a-id", "dataset-a"
    )
    state = parse_qs(urlparse(url).query)["state"][0]
    result = service.complete_authorization(
        "user-a", state, binding, code="one-time-code"
    )
    attempt_key = service._attempt_key(result["attempt_id"])
    sealed = radar_redis.get(attempt_key)
    assert sealed
    assert b"access-secret" not in sealed
    assert b"refresh-secret" not in sealed
    assert 0 < radar_redis.ttl(attempt_key) <= 3600
    with pytest.raises(Exception, match="already used"):
        service.complete_authorization(
            "user-a", state, binding, code="reused-code"
        )


@pytest.mark.parametrize(
    "wrong_user,wrong_binding",
    [("user-b", "binding-a"), ("user-a", "wrong-browser")],
)
def test_state_rejects_wrong_user_or_browser(
    radar_oauth_config, radar_redis, wrong_user, wrong_binding
):
    service = _service(radar_redis)
    url, binding, _ = service.authorization_url(
        "user-a", "dataset-a", "dataset-a", session_binding="binding-a"
    )
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(Exception, match="another user|session binding"):
        service.complete_authorization(
            wrong_user, state, wrong_binding, code="code"
        )


def test_expired_or_invalid_state_is_rejected(radar_oauth_config, radar_redis):
    service = _service(radar_redis)
    url, binding, state_id = service.authorization_url(
        "user-a", "dataset-a", "dataset-a"
    )
    radar_redis.delete(service._state_key(state_id))
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(Exception, match="invalid, expired"):
        service.complete_authorization("user-a", state, binding, code="code")
    with pytest.raises(Exception, match="invalid, expired"):
        service.complete_authorization(
            "user-a", "invalid-state", binding, code="code"
        )


def test_state_is_environment_specific(radar_oauth_config, radar_redis):
    from ckanext.dataset_transfer.services.radar_oauth import RadarOAuthService

    test_service = _service(radar_redis)
    url, binding, _ = test_service.authorization_url(
        "user-a", "dataset-a", "dataset-a"
    )
    other_config = dict(radar_oauth_config)
    other_config["ckanext.dataset_transfer.radar.oauth_environment"] = "custom"
    other_service = RadarOAuthService(
        config=other_config, redis_client=radar_redis,
        request_session=FakeOAuthSession([]),
    )
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(Exception, match="invalid, expired"):
        other_service.complete_authorization(
            "user-a", state, binding, code="code"
        )


def test_pkce_s256_is_preserved(radar_oauth_config, radar_redis, monkeypatch):
    import ckan.plugins.toolkit as toolkit

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.oauth_pkce_enabled",
        "true",
    )
    service = _service(radar_redis)
    url, _, _ = service.authorization_url("user", "dataset", "dataset")
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43


def test_dataset_user_and_browser_binding_prevent_reuse(
    radar_oauth_config, radar_redis
):
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarReauthenticationRequired,
    )

    service = _service(radar_redis)
    _store_attempt(service)
    assert service.get_valid_access_token(
        "user-a", "dataset-a", "binding-a", "attempt-a"
    ) == "access-a"
    for user, dataset, binding in (
        ("user-a", "dataset-b", "binding-a"),
        ("user-b", "dataset-a", "binding-a"),
        ("user-a", "dataset-a", "binding-b"),
    ):
        with pytest.raises(RadarReauthenticationRequired):
            service.get_valid_access_token(
                user, dataset, binding, "attempt-a"
            )


def test_two_dataset_tabs_have_isolated_attempts(radar_oauth_config, radar_redis):
    service = _service(radar_redis)
    _store_attempt(
        service, dataset="dataset-a", binding="tab-a", attempt="attempt-a",
        access="token-a"
    )
    _store_attempt(
        service, dataset="dataset-b", binding="tab-b", attempt="attempt-b",
        access="token-b"
    )
    assert service.get_valid_access_token(
        "user-a", "dataset-a", "tab-a", "attempt-a"
    ) == "token-a"
    assert service.get_valid_access_token(
        "user-a", "dataset-b", "tab-b", "attempt-b"
    ) == "token-b"
    service.disconnect("user-a", "dataset-a", "tab-a", "attempt-a")
    assert service.connection_status(
        "user-a", "dataset-a", "tab-a", "attempt-a"
    )["connected"] is False
    assert service.connection_status(
        "user-a", "dataset-b", "tab-b", "attempt-b"
    )["connected"] is True


def test_expired_token_refreshes_and_rotates_without_extending_attempt_ttl(
    radar_oauth_config, radar_redis
):
    service = _service(radar_redis, [FakeResponse(200, {
        "access_token": "new-access",
        "refresh_token": "rotated-refresh",
        "expires_in": 7200,
    })])
    _store_attempt(service, expires_in=1)
    key = service._attempt_key("attempt-a")
    record = service._open_json(radar_redis.get(key))
    record["expires_at"] = service._timestamp() - 1
    radar_redis.set(key, service._seal_json(record), ex=1200)
    ttl_before = radar_redis.ttl(key)
    assert service.get_valid_access_token(
        "user-a", "dataset-a", "binding-a", "attempt-a"
    ) == "new-access"
    updated = service._open_json(radar_redis.get(key))
    assert updated["refresh_token"] == "rotated-refresh"
    assert radar_redis.ttl(key) <= ttl_before


def test_refresh_without_rotation_preserves_refresh_token(
    radar_oauth_config, radar_redis
):
    service = _service(radar_redis, [FakeResponse(200, {
        "access_token": "new-access", "expires_in": 3600
    })])
    _store_attempt(service, refresh="keep-me", expires_in=1)
    key = service._attempt_key("attempt-a")
    record = service._open_json(radar_redis.get(key))
    record["expires_at"] = service._timestamp() - 1
    radar_redis.set(key, service._seal_json(record), ex=1200)
    service.get_valid_access_token(
        "user-a", "dataset-a", "binding-a", "attempt-a"
    )
    assert service._open_json(radar_redis.get(key))["refresh_token"] == "keep-me"


@pytest.mark.parametrize("failure", [FakeResponse(401, {}), FakeResponse(429, {})])
def test_refresh_failure_is_handled_safely(
    radar_oauth_config, radar_redis, failure
):
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthTemporaryError,
        RadarReauthenticationRequired,
    )

    service = _service(radar_redis, [failure])
    _store_attempt(service, expires_in=1)
    key = service._attempt_key("attempt-a")
    record = service._open_json(radar_redis.get(key))
    record["expires_at"] = service._timestamp() - 1
    radar_redis.set(key, service._seal_json(record), ex=1200)
    error = (
        RadarReauthenticationRequired
        if failure.status_code == 401
        else RadarOAuthTemporaryError
    )
    with pytest.raises(error):
        service.get_valid_access_token(
            "user-a", "dataset-a", "binding-a", "attempt-a"
        )


def test_attempt_claim_is_atomic_and_cleanup_is_terminal(
    radar_oauth_config, radar_redis
):
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthAttemptClaimed,
        RadarReauthenticationRequired,
    )

    service = _service(radar_redis)
    _store_attempt(service)
    service.claim_attempt("user-a", "dataset-a", "binding-a", "attempt-a")
    with pytest.raises(RadarOAuthAttemptClaimed):
        service.claim_attempt("user-a", "dataset-a", "binding-a", "attempt-a")
    assert radar_redis.ttl(service._attempt_key("attempt-a")) <= 7200
    provider = service.token_provider(
        "user-a", "dataset-a", "binding-a", "attempt-a"
    )
    assert provider.get_valid_access_token() == "access-a"
    service.finish_attempt("attempt-a")
    with pytest.raises(RadarReauthenticationRequired):
        service.get_valid_access_token(
            "user-a", "dataset-a", "binding-a", "attempt-a"
        )


def test_disconnect_cannot_interrupt_claimed_publication(
    radar_oauth_config, radar_redis
):
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthAttemptClaimed,
    )

    service = _service(radar_redis)
    _store_attempt(service)
    service.claim_attempt("user-a", "dataset-a", "binding-a", "attempt-a")
    with pytest.raises(RadarOAuthAttemptClaimed):
        service.disconnect("user-a", "dataset-a", "binding-a", "attempt-a")
    assert radar_redis.exists(service._attempt_key("attempt-a"))


def test_no_shared_credential_fallback(radar_oauth_config):
    from ckanext.dataset_transfer.services.radar import RadarConfigError, RadarPublisher

    config = dict(radar_oauth_config)
    config["ckanext.dataset_transfer.radar.access_token"] = "shared-token"
    with pytest.raises(RadarConfigError):
        RadarPublisher(config=config)


def test_environment_mismatch_is_rejected(radar_oauth_config, radar_redis):
    from ckanext.dataset_transfer.services.radar_oauth import (
        RadarOAuthConfigError,
        RadarOAuthService,
    )

    config = dict(radar_oauth_config)
    config["ckanext.dataset_transfer.radar.context_url"] = (
        "https://www.radar-service.eu/radar"
    )
    with pytest.raises(RadarOAuthConfigError):
        RadarOAuthService(config=config, redis_client=radar_redis)


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
def test_callback_and_page_status_are_dataset_specific(
    app, monkeypatch, radar_oauth_config, radar_redis
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services import radar_oauth

    user = factories.SysadminWithToken()
    dataset_a = factories.Dataset()
    dataset_b = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset_a)
    monkeypatch.setattr(
        radar_oauth.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {
            "access_token": "dataset-a-token",
            "refresh_token": "dataset-a-refresh",
            "expires_in": 3600,
        }),
    )
    callback = client.get(
        "/dataset_transfer/radar/callback?code=code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(user),
        status=302,
        follow_redirects=False,
    )
    assert dataset_a["name"] in callback.location
    page_a = client.get(
        "/dataset_transfer/publish_page/{}?publish_target=radar".format(
            dataset_a["name"]
        ),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    page_b = client.get(
        "/dataset_transfer/publish_page/{}?publish_target=radar".format(
            dataset_b["name"]
        ),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    assert "RADAR4Ing authorization successful" in page_a
    assert 'data-radar-connected="true"' in page_a
    assert "Connect your RADAR4Ing account" in page_b
    assert 'data-radar-connected="false"' in page_b
    assert "dataset-a-token" not in page_a


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_disconnect_requires_csrf_and_removes_only_current_dataset(
    app, monkeypatch, radar_oauth_config, radar_redis
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services import radar_oauth

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    _, query, client = _begin_oauth(app, user, dataset)
    monkeypatch.setattr(
        radar_oauth.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200, {
            "access_token": "access", "refresh_token": "refresh", "expires_in": 3600
        }),
    )
    client.get(
        "/dataset_transfer/radar/callback?code=code&state={}".format(
            query["state"][0]
        ),
        headers=_auth_headers(user),
        follow_redirects=False,
    )
    page = client.get(
        "/dataset_transfer/publish_page/{}?publish_target=radar".format(
            dataset["name"]
        ),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    csrf = re.search(r'name="_csrf_token" value="([^"]+)"', page)
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
    disconnected = client.get(
        "/dataset_transfer/publish_page/{}?publish_target=radar".format(
            dataset["name"]
        ),
        headers=_auth_headers(user),
    ).get_data(as_text=True)
    assert 'data-radar-connected="false"' in disconnected


def test_frontend_preserves_metadata_navigation_and_cleans_up_cancel():
    source = (
        Path(__file__).parents[1] / "public" / "transfer.js"
    ).read_text(encoding="utf-8")
    assert "data('radar-connected') !== true" in source
    assert "radar_cancel_disconnect_form" in source
    assert "let radarSectionOrder = ['dataset', 'creators', 'classification', 'rights', 'funding'];" in source
    assert "formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));" in source
    assert "radar.user_password" not in source
    assert "radar.user_name" not in source


def test_oauth_service_has_no_database_model_dependency():
    service_source = (
        Path(__file__).parents[1] / "services" / "radar_oauth.py"
    ).read_text(encoding="utf-8")
    migration_source = (
        Path(__file__).parents[1]
        / "migration" / "dataset_transfer" / "versions"
        / "8c7e4d91a2f0_add_radar_oauth_tables.py"
    ).read_text(encoding="utf-8")
    assert "RadarOAuthToken" not in service_source
    assert "models.radar_oauth" not in service_source
    assert "ckan.model" not in service_source
    assert "op.create_table" not in migration_source
    assert "op.drop_table" not in migration_source


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_compatibility_revision_creates_no_oauth_tables(radar_redis):
    import sqlalchemy as sa
    from ckan.model import meta

    inspector = sa.inspect(meta.Session.bind)
    assert not inspector.has_table("radar_oauth_token")
    assert not inspector.has_table("radar_oauth_state")


@pytest.mark.usefixtures("clean_db")
def test_redis_oauth_service_works_without_extension_migration(
    radar_oauth_config, radar_redis
):
    service = _service(radar_redis)
    _store_attempt(service)
    assert service.get_valid_access_token(
        "user-a", "dataset-a", "binding-a", "attempt-a"
    ) == "access-a"
