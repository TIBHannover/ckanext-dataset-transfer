import pytest
import requests

from ckanext.dataset_transfer.services.radar import (
    RadarPublisher,
    RadarStatusError,
    normalize_radar_status,
)
from ckanext.dataset_transfer.services.radar_status import RadarStatusService


class Response(object):
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session(object):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def publisher_config(**overrides):
    config = {
        "ckanext.dataset_transfer.radar.context_url":
            "https://test.radar-service.eu/radar",
        "ckanext.dataset_transfer.radar.workspace_id": "workspace-id",
        "ckanext.dataset_transfer.radar.responsible_email": "data@example.test",
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize(
    "raw,normalized,label",
    [
        ("PENDING", "PENDING", "Pending"),
        ("IN_REVIEW", "IN_REVIEW", "In Review"),
        ("REVIEW", "IN_REVIEW", "In Review"),
        ("PUBLISHED", "PUBLISHED", "Published"),
        ("ARCHIVED", "ARCHIVED", "Archived"),
        ("QUALITY_CHECK", "QUALITY_CHECK", "Quality Check"),
    ],
)
def test_normalize_radar_status(raw, normalized, label):
    assert normalize_radar_status(raw) == {
        "repository_status": normalized,
        "repository_status_raw": raw,
        "repository_status_label": label,
    }


def test_status_lookup_uses_trusted_context_and_is_read_only():
    session = Session([Response(payload={"id": "radar-id", "state": "IN_REVIEW"})])
    publisher = RadarPublisher(
        publisher_config(), session, access_token="server-token"
    )

    result = publisher.get_dataset_status("radar-id")

    assert result["repository_status"] == "IN_REVIEW"
    assert session.calls == [(
        "https://test.radar-service.eu/radar/api/datasets/radar-id",
        {"timeout": 10.0, "headers": {"Authorization": "Bearer server-token"}},
    )]


def test_status_lookup_quotes_identifier_as_one_path_segment():
    session = Session([Response(payload={"state": "PENDING"})])
    publisher = RadarPublisher(
        publisher_config(), session, access_token="server-token"
    )

    publisher.get_dataset_status("unexpected/path?query=true")

    assert session.calls[0][0] == (
        "https://test.radar-service.eu/radar/api/datasets/"
        "unexpected%2Fpath%3Fquery%3Dtrue"
    )


@pytest.mark.parametrize(
    "response,code",
    [
        (Response(401, {}), "authentication_failed"),
        (Response(403, {}), "authorization_failed"),
        (Response(404, {}), "dataset_not_found"),
        (Response(429, {}), "rate_limited"),
        (Response(500, {}), "service_unavailable"),
        (Response(200, ValueError("bad json")), "invalid_response"),
        (Response(200, {"unexpected": "value"}), "invalid_response"),
        (requests.Timeout("secret response"), "timeout"),
        (requests.ConnectionError("secret response"), "connection_error"),
    ],
)
def test_status_lookup_failures_are_sanitized(response, code):
    publisher = RadarPublisher(
        publisher_config(), Session([response]), access_token="server-token"
    )

    with pytest.raises(RadarStatusError) as caught:
        publisher.get_dataset_status("radar-id")

    assert caught.value.code == code
    assert "secret response" not in str(caught.value)


@pytest.fixture(autouse=True)
def clear_status_cache():
    RadarStatusService.clear_cache()
    yield
    RadarStatusService.clear_cache()


def test_status_service_caches_and_refreshes(monkeypatch):
    from ckanext.dataset_transfer.services import radar_status

    calls = []

    class Publisher(object):
        def __init__(self, **kwargs):
            pass

        def get_dataset_status(self, dataset_id):
            calls.append(dataset_id)
            state = "PENDING" if len(calls) == 1 else "PUBLISHED"
            return normalize_radar_status(state)

    monkeypatch.setattr(radar_status, "RadarPublisher", Publisher)
    monkeypatch.setattr(radar_status, "RadarTokenProvider", lambda config: object())
    monkeypatch.setitem(
        radar_status.toolkit.config,
        "ckanext.dataset_transfer.radar.context_url",
        "https://test.radar-service.eu/radar",
    )
    monkeypatch.setitem(
        radar_status.toolkit.config,
        "ckanext.dataset_transfer.radar.status_cache_ttl",
        300,
    )

    first = RadarStatusService.lookup("radar-id")
    cached = RadarStatusService.lookup("radar-id")
    refreshed = RadarStatusService.lookup("radar-id", refresh=True)

    assert first["repository_status"] == "PENDING"
    assert first["repository_status_source"] == "radar_api"
    assert cached["repository_status"] == "PENDING"
    assert cached["repository_status_source"] == "cache"
    assert refreshed["repository_status"] == "PUBLISHED"
    assert calls == ["radar-id", "radar-id"]


def test_failed_refresh_returns_explicitly_stale_cached_status(monkeypatch):
    from ckanext.dataset_transfer.services import radar_status

    calls = []

    class Publisher(object):
        def __init__(self, **kwargs):
            pass

        def get_dataset_status(self, dataset_id):
            calls.append(dataset_id)
            if len(calls) == 1:
                return normalize_radar_status("IN_REVIEW")
            raise RadarStatusError("service_unavailable", "safe")

    monkeypatch.setattr(radar_status, "RadarPublisher", Publisher)
    monkeypatch.setattr(radar_status, "RadarTokenProvider", lambda config: object())
    monkeypatch.setitem(
        radar_status.toolkit.config,
        "ckanext.dataset_transfer.radar.context_url",
        "https://test.radar-service.eu/radar",
    )

    first = RadarStatusService.lookup("radar-id")
    stale = RadarStatusService.lookup("radar-id", refresh=True)

    assert stale["repository_status"] == "IN_REVIEW"
    assert stale["repository_status_checked_at"] == first[
        "repository_status_checked_at"
    ]
    assert stale["repository_status_available"] is False
    assert stale["repository_status_source"] == "stale_cache"
    assert stale["repository_status_error"] == "service_unavailable"

