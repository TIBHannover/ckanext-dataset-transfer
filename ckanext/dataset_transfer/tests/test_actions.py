import pytest


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "dataset_transfer"),
    pytest.mark.ckan_config("ckan.auth.create_unowned_dataset", True),
    pytest.mark.usefixtures("clean_db", "with_plugins"),
]


@pytest.fixture(autouse=True)
def ensure_extension_table(clean_db):
    """CKAN's core clean_db fixture does not run extension migrations."""
    from ckan.model import meta
    from ckanext.dataset_transfer.models.published_dataset import (
        published_dataset_table,
    )

    published_dataset_table.create(bind=meta.engine, checkfirst=True)
    yield
    published_dataset_table.drop(bind=meta.engine, checkfirst=True)


def test_targets_requires_auth(app):
    response = app.post("/api/3/action/dataset_transfer_targets", json={}, status=403)
    assert response.json["success"] is False


def test_targets_with_api_token(app, monkeypatch):
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit
    user = factories.UserWithToken()
    monkeypatch.setitem(toolkit.config, "ckanext.dataset_transfer.radar.enabled", True)
    response = app.post("/api/3/action/dataset_transfer_targets", json={},
                        headers={"Authorization": user["token"]})
    assert response.json["success"] is True
    assert response.json["result"]["targets"] == [
        {"id": "radar", "name": "RADAR4Ing", "enabled": True},
        {"id": "luh", "name": "LUH Research Data Repository", "enabled": True},
    ]


def test_publish_requires_strict_boolean_consent(app, monkeypatch):
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit
    sysadmin = factories.SysadminWithToken()
    package = factories.Dataset()
    monkeypatch.setitem(toolkit.config, "ckanext.dataset_transfer.radar.enabled", True)
    response = app.post("/api/3/action/dataset_transfer_publish", json={
        "dataset_id": package["id"], "target": "radar",
        "terms_accepted": "true", "rights_confirmed": True,
    }, headers={"Authorization": sysadmin["token"]}, status=409)
    assert response.json["success"] is False
    assert "consent" in response.json["error"]


def test_validate_enforces_dataset_update_permission(app, monkeypatch):
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit
    user = factories.UserWithToken()
    organization = factories.Organization()
    package = factories.Dataset(owner_org=organization["id"])
    monkeypatch.setitem(toolkit.config, "ckanext.dataset_transfer.radar.enabled", True)
    response = app.post("/api/3/action/dataset_transfer_validate", json={
        "dataset_id": package["id"], "target": "radar",
    }, headers={"Authorization": user["token"]}, status=403)
    assert response.json["success"] is False


def _published_record(dataset_id, target, destination_id):
    from datetime import datetime
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    record = PublishedDataset(
        dataset_id=dataset_id,
        doi="10.80836/example",
        published_url="https://radar.example/dataset/{}".format(destination_id),
        published_dataset_id=PublishedDataset.encode_target_id(
            target, destination_id
        ),
        publish_time=datetime.utcnow(),
    )
    record.save()
    return record


def test_status_action_requires_authentication(app):
    import ckan.tests.factories as factories

    package = factories.Dataset()
    response = app.post(
        "/api/3/action/dataset_transfer_status",
        json={"dataset_id": package["id"], "target": "radar"},
        status=403,
    )

    assert response.json["success"] is False


def test_status_action_obeys_package_show_permission(app):
    import ckan.tests.factories as factories

    owner = factories.Organization()
    package = factories.Dataset(owner_org=owner["id"], private=True)
    other_user = factories.UserWithToken()
    response = app.post(
        "/api/3/action/dataset_transfer_status",
        json={"dataset_id": package["id"], "target": "radar"},
        headers={"Authorization": other_user["token"]},
        status=403,
    )

    assert response.json["success"] is False


def test_status_action_adds_live_radar_state_without_breaking_legacy_fields(
    app, monkeypatch
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_status import RadarStatusService

    sysadmin = factories.SysadminWithToken()
    package = factories.Dataset()
    _published_record(package["id"], "radar", "radar-id")
    calls = []
    monkeypatch.setattr(
        RadarStatusService,
        "lookup",
        lambda dataset_id, refresh=False: calls.append((dataset_id, refresh)) or {
            "repository_status": "IN_REVIEW",
            "repository_status_raw": "IN_REVIEW",
            "repository_status_label": "In Review",
            "repository_status_available": True,
            "repository_status_source": "radar_api",
            "repository_status_checked_at": "2026-11-26T16:30:00Z",
            "repository_status_error": None,
        },
    )

    response = app.post(
        "/api/3/action/dataset_transfer_status",
        json={"dataset_id": package["id"], "target": "radar", "refresh": True},
        headers={"Authorization": sysadmin["token"]},
    )
    result = response.json["result"]

    assert response.json["success"] is True
    assert result["status"] == "pending_publication"
    assert result["transfer_status"] == "transferred"
    assert result["repository_status"] == "IN_REVIEW"
    assert result["repository_status_label"] == "In Review"
    assert result["doi"] == "10.80836/example"
    assert result["destination_dataset_id"] == "radar-id"
    assert calls == [("radar-id", True)]


def test_status_action_rejects_non_boolean_refresh(app):
    import ckan.tests.factories as factories

    sysadmin = factories.SysadminWithToken()
    package = factories.Dataset()
    response = app.post(
        "/api/3/action/dataset_transfer_status",
        json={"dataset_id": package["id"], "target": "radar", "refresh": "true"},
        headers={"Authorization": sysadmin["token"]},
        status=409,
    )

    assert "refresh" in response.json["error"]


def test_luh_status_does_not_query_radar(app, monkeypatch):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_status import RadarStatusService

    sysadmin = factories.SysadminWithToken()
    package = factories.Dataset()
    _published_record(package["id"], "luh", "luh-id")
    monkeypatch.setattr(
        RadarStatusService,
        "lookup",
        lambda *args, **kwargs: pytest.fail("RADAR must not be queried for LUH"),
    )

    response = app.post(
        "/api/3/action/dataset_transfer_status",
        json={"dataset_id": package["id"], "target": "luh"},
        headers={"Authorization": sysadmin["token"]},
    )
    result = response.json["result"]

    assert result["status"] == "transferred"
    assert result["transfer_status"] == "transferred"
    assert result["repository_status"] is None


def test_dataset_page_displays_transfer_and_repository_status(app, monkeypatch):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_status import RadarStatusService

    sysadmin = factories.SysadminWithToken()
    package = factories.Dataset()
    _published_record(package["id"], "radar", "radar-id")
    monkeypatch.setattr(
        RadarStatusService,
        "lookup",
        lambda *args, **kwargs: {
            "repository_status": "PUBLISHED",
            "repository_status_raw": "PUBLISHED",
            "repository_status_label": "Published",
            "repository_status_available": True,
            "repository_status_source": "radar_api",
            "repository_status_checked_at": "2026-11-26T16:30:00Z",
            "repository_status_error": None,
        },
    )

    response = app.get(
        "/dataset/{}".format(package["name"]),
        headers={"Authorization": sysadmin["token"]},
    )
    response_text = response.get_data(as_text=True)

    assert "Transfer status" in response_text
    assert "Completed" in response_text
    assert "Repository status" in response_text
    assert "Published" in response_text
    assert "10.80836/example" in response_text
    assert "formal publication status is not tracked" not in response_text


def test_dataset_page_survives_unavailable_radar(app, monkeypatch):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.services.radar_status import RadarStatusService

    package = factories.Dataset()
    _published_record(package["id"], "radar", "radar-id")
    monkeypatch.setattr(
        RadarStatusService,
        "lookup",
        lambda *args, **kwargs: {
            "repository_status": None,
            "repository_status_raw": None,
            "repository_status_label": "Temporarily unavailable",
            "repository_status_available": False,
            "repository_status_source": "unavailable",
            "repository_status_checked_at": "2026-11-26T16:30:00Z",
            "repository_status_error": "timeout",
        },
    )

    response = app.get("/dataset/{}".format(package["name"]))
    response_text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Transfer status" in response_text
    assert "Temporarily unavailable" in response_text
    assert "10.80836/example" in response_text
