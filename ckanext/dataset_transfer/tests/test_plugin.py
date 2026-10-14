import json
import re
from urllib.parse import urlparse

import pytest
import requests


pytestmark = [
    pytest.mark.ckan_config("ckan.plugins", "dataset_transfer"),
    pytest.mark.usefixtures("with_plugins"),
]


class FakeResponse(object):
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def fail_real_outbound_requests(monkeypatch):
    allowed_hosts = {"solr", "localhost", "127.0.0.1", "ckan"}

    def blocked_request(self, method, url, **kwargs):
        if urlparse(url).hostname in allowed_hosts:
            return original_request(self, method, url, **kwargs)
        raise AssertionError(
            "Unexpected real outbound HTTP request during dataset_transfer tests: "
            "{} {}".format(method, url)
        )

    original_request = requests.sessions.Session.request
    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)


@pytest.fixture
def dataset_transfer_migrated_db(clean_db):
    import ckan.cli.db as db
    import ckan.plugins as plugins

    if not plugins.plugin_loaded("dataset_transfer"):
        plugins.load("dataset_transfer")

    db._run_migrations("dataset_transfer", None, True)


@pytest.fixture
def csrf_enforced_app(app, with_plugins, monkeypatch):
    flask_app = app.flask_app
    csrf = flask_app.extensions["csrf"]
    blueprint = flask_app.blueprints["dataset_transfer"]
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_CHECK_DEFAULT", True)
    hooks = flask_app.before_request_funcs.setdefault(blueprint.name, [])
    protect = csrf.protect
    hooks.insert(0, protect)
    yield app
    hooks.remove(protect)


def _body(response):
    if hasattr(response, "text"):
        return response.text
    if isinstance(response.body, bytes):
        return response.body.decode("utf-8")
    return response.body


def _auth_headers(user):
    return {"Authorization": user["token"]}


def test_plugin_loads():
    import ckan.plugins as plugins

    assert plugins.plugin_loaded("dataset_transfer")


def test_database_migration_initializes_tables(dataset_transfer_migrated_db):
    import ckan.model as model
    import sqlalchemy as sa

    inspector = sa.inspect(model.Session.bind)

    assert inspector.has_table("published_dataset")
    assert inspector.has_table("publish_api_token")


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_page_renders_for_editor(app):
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit

    user = factories.SysadminWithToken()
    dataset = factories.Dataset(
        title="Migration test dataset",
        author="Author",
        author_email="author@example.test",
        maintainer="Maintainer",
        maintainer_email="maintainer@example.test",
    )

    url = toolkit.url_for(
        "dataset_transfer.publish_page", dataset_name=dataset["name"]
    )
    response = app.get(url, headers=_auth_headers(user))

    assert response.status_code == 200, _body(response)
    assert "Publish the dataset" in _body(response)
    assert 'id="publish_url"' in _body(response)


@pytest.mark.ckan_config("SECRET_KEY", "dataset-transfer-test-secret")
@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_post_accepts_csrf_token_from_rendered_page(
    csrf_enforced_app, monkeypatch
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.Sysadmin()
    dataset = factories.Dataset(user=user)
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )
    client = csrf_enforced_app.test_client()
    page = client.get(
        "/dataset_transfer/publish_page/{}".format(dataset["name"]),
        extra_environ={"REMOTE_USER": user["name"]},
    )
    page_body = page.get_data(as_text=True)
    token_match = re.search(
        r'<meta name="_csrf_token" content="([^"]+)"', page_body
    )
    assert token_match, page_body

    missing_token = client.post(
        "/dataset_transfer/publish",
        data={"package_id": dataset["id"]},
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert missing_token.status_code == 400
    assert "CSRF token is missing" in missing_token.get_data(as_text=True)

    response = client.post(
        "/dataset_transfer/publish",
        data={
            "_csrf_token": token_match.group(1),
            "package_id": dataset["id"],
            "publish_target": "radar",
            "terms_of_usage": "false",
            "rights_of_use": "true",
        },
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert response.status_code == 400
    assert response.json["error"] == "Missing consent"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_user_has_api_token_route_returns_false_for_authenticated_user(app):
    import ckan.tests.factories as factories

    user = factories.SysadminWithToken()

    response = app.get(
        "/dataset_transfer/user_has_api_token",
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    assert _body(response) == "False"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_rejects_missing_consent_with_json_error(app):
    import ckan.tests.factories as factories

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "api_token": "token",
            "save_api_token_box": "false",
            "token_exist_box": "false",
            "terms_of_usage": "false",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 400
    assert response.json == {
        "success": False,
        "error": "Missing consent",
        "message": "Terms of usage and rights of use must be accepted.",
    }


def test_load_publish_form_data_uses_mocked_remote_api(app, monkeypatch):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    calls = []
    original_get = requests.get

    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )

    def fake_get(url, headers=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, **kwargs)
        calls.append((url, headers, kwargs))
        return FakeResponse(
            200,
            {
                "success": True,
                "result": [
                    {"name": "sfb_1153", "title": "SFB 1153"},
                    {"name": "sfb_1368", "title": "SFB 1368"},
                ]
            },
        )

    monkeypatch.setattr(base.requests, "get", fake_get)

    response = app.post(
        "/dataset_transfer/load_publish_form_data",
        params={
            "package_id": "dataset-id",
            "api_token": "token",
            "token_exist_box": "false",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    assert json.loads(_body(response)) == [
        {"id": "sfb_1153", "text": "SFB 1153"},
        {"id": "sfb_1368", "text": "SFB 1368"},
    ]
    assert calls[0][0].endswith("/organization_list_for_user")


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_dataset_with_url_and_uploaded_resources_uses_mocked_api(
    app, monkeypatch, tmp_path
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    user = factories.SysadminWithToken()
    storage_path = tmp_path / "ckan-storage"
    upload_id = "abcdef1234567890abcdef1234567890"
    upload_dir = storage_path / "resources" / upload_id[:3] / upload_id[3:6]
    upload_dir.mkdir(parents=True)
    (upload_dir / upload_id[6:]).write_bytes(b"uploaded resource data")

    dataset = {
        "id": "local-dataset-id",
        "name": "local-dataset",
        "title": "Local Dataset",
        "notes": "Test dataset",
        "resources": [
            {
                "id": "url-resource-id",
                "name": "URL resource",
                "url": "https://example.test/data.csv",
                "url_type": "",
                "datastore_active": True,
            },
            {
                "id": upload_id,
                "name": "Uploaded resource",
                "url": "upload.bin",
                "url_type": "upload",
                "datastore_active": True,
            },
        ],
        "groups": [{"name": "local-group"}],
        "isopen": False,
        "private": True,
        "owner_org": "local-org",
    }
    original_dataset = json.loads(json.dumps(dataset))
    calls = []
    created_resource_count = [0]
    original_get = requests.get

    monkeypatch.setitem(toolkit.config, "ckan.storage_path", str(storage_path))
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )
    monkeypatch.setattr(base.Helper, "get_organization_id", lambda: "sfb_1153")
    monkeypatch.setattr(
        base.toolkit,
        "get_action",
        lambda name: (
            lambda context, data_dict: dataset
            if name == "package_show"
            else pytest.fail("Unexpected CKAN action: {}".format(name))
        ),
    )

    def fake_get(url, headers=None, params=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, params=params, **kwargs)
        calls.append(("GET", url, {"headers": headers, "params": params}))
        assert url.endswith("/organization_show")
        return FakeResponse(
            200, {"success": True, "result": {"id": "target-org-id"}}
        )

    def fake_post(url, headers=None, json=None, data=None, files=None, **kwargs):
        calls.append(
            (
                "POST",
                url,
                {"headers": headers, "json": json, "data": data, "files": files},
            )
        )
        if url.endswith("/package_create"):
            assert json["id"] == ""
            assert json["resources"] == []
            assert json["groups"] == []
            assert json["private"] is False
            assert json["owner_org"] == "target-org-id"
            return FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "target-dataset-id",
                        "name": "target-dataset",
                        "doi": "10.123/test",
                    }
                },
            )
        if url.endswith("/resource_create"):
            created_resource_count[0] += 1
            assert json["package_id"] == "target-dataset-id"
            assert "datastore_active" not in json
            return FakeResponse(
                200, {"result": {"id": "target-resource-{}".format(created_resource_count[0])}}
            )
        if url.endswith("/resource_patch"):
            assert data == {"id": "target-resource-2"}
            assert files["upload"] == b"uploaded resource data"
            return FakeResponse(200, {"result": {"id": "target-resource-2"}})
        pytest.fail("Unexpected remote post: {}".format(url))

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base.requests, "post", fake_post)

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "api_token": " token ",
            "save_api_token_box": "false",
            "token_exist_box": "false",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["doi"] == "10.123/test"
    assert response.json["published_url"].endswith("/dataset/target-dataset")
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == [
        "organization_show",
        "package_create",
        "resource_create",
        "resource_create",
        "resource_patch",
    ]
    assert dataset == original_dataset
    assert PublishedDataset.get_by_dataset("local-dataset-id").doi == "10.123/test"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_dataset_to_radar_uses_mocked_api(app, monkeypatch, tmp_path):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    user = factories.SysadminWithToken()
    storage_path = tmp_path / "ckan-storage"
    upload_id = "fedcba1234567890fedcba1234567890"
    upload_dir = storage_path / "resources" / upload_id[:3] / upload_id[3:6]
    upload_dir.mkdir(parents=True)
    (upload_dir / upload_id[6:]).write_bytes(b"radar resource data")

    dataset = {
        "id": "local-radar-dataset-id",
        "name": "local-radar-dataset",
        "title": "Local RADAR Dataset",
        "notes": "Dataset to test RADAR publishing",
        "author": "Radar Author",
        "author_email": "author@example.test",
        "maintainer": "Radar Maintainer",
        "maintainer_email": "maintainer@example.test",
        "tags": [{"name": "radar"}, {"display_name": "ckan"}],
        "resources": [
            {
                "id": upload_id,
                "name": "radar-upload.txt",
                "url": "radar-upload.txt",
                "url_type": "upload",
            }
        ],
    }
    calls = []
    original_get = requests.get

    monkeypatch.setitem(toolkit.config, "ckan.storage_path", str(storage_path))
    monkeypatch.setitem(toolkit.config, "ckan.site_url", "https://ckan.example.test")
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.context_url",
        "https://test.radar-service.eu/radar",
    )
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.workspace_id",
        "workspace-id",
    )
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.responsible_email",
        "data@example.test",
    )
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.access_token",
        "radar-access-token",
    )
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )
    monkeypatch.setattr(
        base.toolkit,
        "get_action",
        lambda name: (
            lambda context, data_dict: dataset
            if name == "package_show"
            else pytest.fail("Unexpected CKAN action: {}".format(name))
        ),
    )

    def fake_post(url, headers=None, json=None, files=None, **kwargs):
        calls.append(("POST", url, {"headers": headers, "json": json, "files": files}))
        if url.endswith("/api/workspaces/workspace-id/datasets"):
            assert headers["Authorization"] == "Bearer radar-access-token"
            assert json["parentId"] == "workspace-id"
            assert json["technicalMetadata"]["schema"] == {"key": "RDDM", "version": "9.3"}
            assert json["technicalMetadata"]["publicationBacklink"].endswith(
                "/dataset/local-radar-dataset"
            )
            return FakeResponse(200, {"id": "radar-dataset-id"})
        if url.endswith("/api/datasets/radar-dataset-id/metadata"):
            metadata = files["metadataFile"][1]
            assert b"Local RADAR Dataset" in metadata
            assert b"Radar Author" in metadata
            return FakeResponse(200, {"success": True})
        if url.endswith("/radar-ingest/upload/radar-dataset-id/ingest"):
            archive = files["file"][1]
            assert archive.getvalue()
            return FakeResponse(200, {"success": True})
        pytest.fail("Unexpected RADAR post: {}".format(url))

    def fake_get(url, headers=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, **kwargs)
        calls.append(("GET", url, {"headers": headers}))
        if url.endswith("/api/datasets/radar-dataset-id/metadata/validate"):
            return FakeResponse(200, {"valid": True})
        if url.endswith("/api/datasets/radar-dataset-id/doi"):
            return FakeResponse(200, {"doi": "10.123/radar"})
        pytest.fail("Unexpected RADAR get: {}".format(url))

    monkeypatch.setattr(base.requests, "post", fake_post)
    monkeypatch.setattr(base.requests, "get", fake_get)

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "publish_target": "radar",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["doi"] == "10.123/radar"
    assert response.json["published_dataset_id"] == "radar-dataset-id"
    assert [call[0] for call in calls] == ["POST", "POST", "GET", "POST", "GET"]
    assert PublishedDataset.get_by_dataset("local-radar-dataset-id").doi == "10.123/radar"


def test_unmocked_requests_are_blocked():
    with pytest.raises(AssertionError):
        requests.post("https://data.uni-hannover.de/api/3/action/package_create")
