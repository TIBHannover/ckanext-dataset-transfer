import pytest


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "dataset_transfer"),
    pytest.mark.usefixtures("clean_db", "with_plugins"),
]


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
