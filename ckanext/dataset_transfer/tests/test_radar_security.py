import pytest
import requests

from ckanext.dataset_transfer.services.radar import (
    RadarConfigError,
    RadarPublishError,
    RadarPublisher,
    _log_response,
)
from ckanext.dataset_transfer.services.radar_auth import (
    RadarAuthConfigError,
    RadarAuthenticationError,
    RadarTokenProvider,
)


class Response(object):
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self.payload = payload
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("post", url, self._snapshot(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        self.calls.append(("get", url, self._snapshot(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @staticmethod
    def _snapshot(kwargs):
        snapshot = dict(kwargs)
        if "headers" in snapshot:
            snapshot["headers"] = dict(snapshot["headers"])
        return snapshot


def auth_config(**overrides):
    config = {
        "ckanext.dataset_transfer.radar.context_url": "https://test.radar-service.eu/radar",
        "ckanext.dataset_transfer.radar.client_id": "client-id-secret",
        "ckanext.dataset_transfer.radar.client_secret": "client-secret-value",
        "ckanext.dataset_transfer.radar.redirect_url": "https://www.tib.eu",
        "ckanext.dataset_transfer.radar.user_name": "technical-user",
        "ckanext.dataset_transfer.radar.user_password": "password-value",
    }
    config.update(overrides)
    return config


def publisher_config(**overrides):
    config = auth_config()
    config.update({
        "ckanext.dataset_transfer.radar.workspace_id": "workspace-id",
        "ckanext.dataset_transfer.radar.responsible_email": "data@example.test",
    })
    config.update(overrides)
    return config


def test_token_acquisition_reuse_and_expiration():
    now = [1000]
    session = Session([
        Response(200, {"accessToken": "first-token", "expiresIn": 100}),
        Response(200, {"access_token": "second-token", "expires_in": 100}),
    ])
    provider = RadarTokenProvider(auth_config(), session, clock=lambda: now[0])

    assert provider.get_valid_access_token() == "first-token"
    assert provider.get_valid_access_token() == "first-token"
    assert len(session.calls) == 1
    now[0] = 1091
    assert provider.get_valid_access_token() == "second-token"
    assert len(session.calls) == 2
    assert session.calls[0][1].endswith("/radar/api/tokens")


def test_exact_deployment_environment_variable_names_are_supported(monkeypatch):
    values = {
        "CKANEXT_DATASET_TRANSFER_RADAR_CONTEXT_URL":
            "https://test.radar-service.eu/radar",
        "CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_ID": "client-id",
        "CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_SECRET": "client-secret",
        "CKANEXT_DATASET_TRANSFER_RADAR_REDIRECT_URL": "https://www.tib.eu",
        "CKANEXT_DATASET_TRANSFER_RADAR_USER_NAME": "technical-user",
        "CKANEXT_DATASET_TRANSFER_RADAR_USER_PASSWORD": "password",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    session = Session([Response(200, {"accessToken": "token"})])

    provider = RadarTokenProvider({}, session)

    assert provider.get_valid_access_token() == "token"
    assert session.calls[0][2]["json"] == {
        "clientId": "client-id",
        "clientSecret": "client-secret",
        "redirectUrl": "https://www.tib.eu",
        "userName": "technical-user",
        "userPassword": "password",
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("ckanext.dataset_transfer.radar.client_id", ""),
        ("ckanext.dataset_transfer.radar.client_secret", "${RADAR_SECRET}"),
        ("ckanext.dataset_transfer.radar.user_name", "{{RADAR_USER}}"),
        ("ckanext.dataset_transfer.radar.user_password", ""),
    ],
)
def test_missing_or_unresolved_credentials_are_rejected(monkeypatch, key, value):
    for env_key in RadarTokenProvider.SETTINGS.values():
        monkeypatch.delenv(env_key[1], raising=False)
    with pytest.raises(RadarAuthConfigError, match="not configured"):
        RadarTokenProvider(auth_config(**{key: value}))


@pytest.mark.parametrize(
    "response,message",
    [
        (Response(401, {"password": "password-value"}), "check the configured credentials"),
        (Response(200, ValueError("bad json")), "invalid response"),
        (Response(200, {"unexpected": "bearer-secret"}), "invalid response"),
        (requests.Timeout("client-secret-value"), "timed out"),
    ],
)
def test_authentication_failures_are_safe(response, message):
    provider = RadarTokenProvider(auth_config(), Session([response]))
    with pytest.raises(RadarAuthenticationError, match=message) as caught:
        provider.get_valid_access_token()
    assert "password-value" not in str(caught.value)
    assert "client-secret-value" not in str(caught.value)
    assert "bearer-secret" not in str(caught.value)


def test_401_invalidates_token_and_retries_once():
    session = Session([
        Response(200, {"accessToken": "expired-token", "expiresIn": 3600}),
        Response(401, {"access_token": "leaked-token"}),
        Response(200, {"accessToken": "fresh-token", "expiresIn": 3600}),
        Response(200, {"id": "remote-id"}),
    ])
    provider = RadarTokenProvider(auth_config(), session)
    publisher = RadarPublisher(publisher_config(), session, token_provider=provider)

    created = publisher._create_dataset({"id": "source-id", "title": "Title"})

    assert created["id"] == "remote-id"
    api_calls = [call for call in session.calls if "/api/tokens" not in call[1]]
    assert len(api_calls) == 2
    assert api_calls[0][2]["headers"]["Authorization"] == "Bearer expired-token"
    assert api_calls[1][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_403_has_safe_workspace_permission_error():
    publisher = RadarPublisher(
        publisher_config(), Session([]), access_token="token"
    )
    with pytest.raises(RadarPublishError, match="permission.*workspace"):
        publisher._raise_for_radar(Response(403, {"secret": "value"}), "failed")


def test_response_logging_never_includes_body_or_url(monkeypatch):
    from ckanext.dataset_transfer.services import radar

    secret = "Bearer top-secret-token"
    response = Response(500, text=secret)
    response.url = "https://example.test/api?clientSecret=secret"
    calls = []
    monkeypatch.setattr(radar.log, "info", lambda *args: calls.append(args))

    _log_response("RADAR operation", response, "dataset-id")

    assert calls == [
        (
            "%s completed status=%s dataset_id=%s",
            "RADAR operation",
            500,
            "dataset-id",
        )
    ]
    logged_values = " ".join(str(value) for value in calls[0])
    assert secret not in logged_values
    assert "clientSecret" not in logged_values


def test_dataset_url_default_custom_and_invalid_template():
    default = RadarPublisher(publisher_config(), Session([]), access_token="token")
    assert default.dataset_url("abc123") == (
        "https://test.radar-service.eu/radar/en/dataset/abc123"
    )
    custom = RadarPublisher(
        publisher_config(**{
            "ckanext.dataset_transfer.radar.dataset_url_template":
                "https://radar.example/en/dataset/{dataset_id}"
        }),
        Session([]),
        access_token="token",
    )
    assert custom.dataset_url("prod123") == "https://radar.example/en/dataset/prod123"
    with pytest.raises(RadarConfigError, match="must contain"):
        RadarPublisher(
            publisher_config(**{
                "ckanext.dataset_transfer.radar.dataset_url_template":
                    "https://radar.example/en/dataset/static"
            }),
            Session([]),
            access_token="token",
        )
