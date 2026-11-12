import json
from pathlib import Path
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


class InvalidJSONResponse(FakeResponse):
    def json(self):
        raise ValueError("invalid JSON")


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
def csrf_enforced_app(app):
    flask_app = app.flask_app
    csrf = flask_app.extensions["csrf"]
    blueprint = flask_app.blueprints["dataset_transfer"]
    blueprint_name = blueprint.name
    exemption_keys = (blueprint, blueprint_name)
    original_enabled = flask_app.config["WTF_CSRF_ENABLED"]
    original_check_default = flask_app.config["WTF_CSRF_CHECK_DEFAULT"]
    original_exemptions = {
        key for key in exemption_keys if key in csrf._exempt_blueprints
    }

    flask_app.config["WTF_CSRF_ENABLED"] = True
    flask_app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    for key in exemption_keys:
        csrf._exempt_blueprints.discard(key)
    try:
        assert flask_app.config["WTF_CSRF_ENABLED"] is True
        assert flask_app.config["WTF_CSRF_CHECK_DEFAULT"] is True
        assert not any(key in csrf._exempt_blueprints for key in exemption_keys)
        yield app
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = original_enabled
        flask_app.config["WTF_CSRF_CHECK_DEFAULT"] = original_check_default
        for key in exemption_keys:
            csrf._exempt_blueprints.discard(key)
        csrf._exempt_blueprints.update(original_exemptions)


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


def test_ajax_posts_use_ckan_csrf_meta_token():
    source = (
        Path(__file__).parents[1] / "public" / "transfer.js"
    ).read_text(encoding="utf-8")

    assert 'meta[name="csrf_field_name"]' in source
    assert "meta[name=\"' + field_name + '\"]" in source
    assert source.count("add_csrf_token(formdata);") == 2


@pytest.mark.parametrize(
    "root_path",
    [None, "/sfb1153/ckan", "/sfb1368/ckan", "/unrelated/reverse-proxy"],
)
def test_target_organization_is_independent_of_root_path(monkeypatch, root_path):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        " configured-destination ",
    )
    if root_path is None:
        monkeypatch.delitem(toolkit.config, "ckan.root_path", raising=False)
    else:
        monkeypatch.setitem(toolkit.config, "ckan.root_path", root_path)

    assert Helper.get_organization_id() == "configured-destination"


def test_destination_urls_are_configurable_and_normalized(monkeypatch):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_api_url",
        " https://destination.example/proxy/api/3/action ",
    )
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_public_url",
        " https://destination.example/proxy ",
    )

    assert Helper.get_target_api_url() == (
        "https://destination.example/proxy/api/3/action/"
    )
    assert Helper.get_target_public_url() == "https://destination.example/proxy/"


def test_destination_settings_are_declared(ckan_config):
    for key in (
        "ckanext.dataset_transfer.target_organization",
        "ckanext.dataset_transfer.target_api_url",
        "ckanext.dataset_transfer.target_public_url",
    ):
        assert ckan_config.is_declared(key)


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
    publish_calls = []
    view_functions = csrf_enforced_app.flask_app.view_functions
    publish_view = view_functions["dataset_transfer.publish"]

    def tracked_publish_view():
        publish_calls.append(True)
        return publish_view()

    monkeypatch.setitem(
        view_functions,
        "dataset_transfer.publish",
        tracked_publish_view,
    )

    missing_token = client.post(
        "/dataset_transfer/publish",
        data={"package_id": dataset["id"]},
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert missing_token.status_code == 400
    assert "CSRF token is missing" in missing_token.get_data(as_text=True)
    assert publish_calls == []

    invalid_token = client.post(
        "/dataset_transfer/publish",
        data={
            "_csrf_token": "invalid-token",
            "package_id": dataset["id"],
        },
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert invalid_token.status_code == 400
    assert "CSRF token is invalid" in invalid_token.get_data(as_text=True)
    assert publish_calls == []

    response = client.post(
        "/dataset_transfer/publish",
        data={
            "_csrf_token": token_match.group(1),
            "package_id": dataset["id"],
            "terms_of_usage": "false",
            "rights_of_use": "true",
        },
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert response.status_code == 400
    assert response.json["error"] == "Missing consent"
    assert publish_calls == [True]

    missing_form_token = client.post(
        "/dataset_transfer/load_publish_form_data",
        data={"package_id": dataset["id"]},
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert missing_form_token.status_code == 400

    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: False
    )
    form_response = client.post(
        "/dataset_transfer/load_publish_form_data",
        data={"_csrf_token": token_match.group(1), "package_id": dataset["id"]},
        extra_environ={"REMOTE_USER": user["name"]},
    )
    assert form_response.status_code == 200
    assert form_response.get_data(as_text=True) == "Not Authorized"

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


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_rejects_user_without_dataset_edit_permission(app, monkeypatch):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "configured-destination",
    )
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: False
    )

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 403
    assert response.json["error"] == "Not Authorized"


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


@pytest.mark.parametrize(
    "instance,target_organization",
    [
        ("SFB1153", "sfb_1153"),
        ("SFB1368", "sfb_1368"),
        # Synthetic value: deployment must replace this only after verification.
        ("TRR375", "verified-trr375-luh-organization"),
    ],
)
@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_dataset_with_url_and_uploaded_resources_uses_mocked_api(
    app, monkeypatch, tmp_path, instance, target_organization
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
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        target_organization,
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

    def fake_get(url, headers=None, params=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, params=params, **kwargs)
        calls.append(("GET", url, {"headers": headers, "params": params}))
        assert headers["Authorization"] == "token"
        if url.endswith("/package_show"):
            assert params == {"id": dataset["name"]}
            return FakeResponse(
                404, {"success": False, "error": {"message": "Not found"}}
            )
        assert url.endswith("/organization_show")
        assert params == {"id": target_organization}
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
            assert "id" not in json
            assert dataset["id"] not in json.values()
            assert json["name"] == dataset["name"]
            assert json["title"] == dataset["title"]
            assert json["notes"] == dataset["notes"]
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
    assert response.json["published_dataset_id"] == "target-dataset-id"
    assert response.json["published_url"].endswith("/dataset/target-dataset")
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == [
        "organization_show",
        "package_show",
        "package_create",
        "resource_create",
        "resource_create",
        "resource_patch",
    ]
    assert dataset == original_dataset
    publication = PublishedDataset.get_by_dataset("local-dataset-id")
    assert publication.dataset_id == "local-dataset-id"
    assert publication.doi == "10.123/test"
    assert PublishedDataset.decode_target_id(publication.published_dataset_id) == (
        "luh",
        "target-dataset-id",
    )


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_luh_publish_fails_closed_without_target_organization(app, monkeypatch):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    monkeypatch.delitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        raising=False,
    )
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 500
    assert response.json["error"] == "Missing configuration"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_remote_organization_error_is_reported_without_creating_dataset(
    app, monkeypatch
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    original_get = requests.get
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "configured-destination",
    )
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )
    def fake_get(url, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, **kwargs)
        return FakeResponse(403, {"success": False, "error": "invalid token"})

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(
        base.requests,
        "post",
        lambda *args, **kwargs: pytest.fail(
            "Dataset creation must not follow a failed organization lookup"
        ),
    )

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "api_token": "invalid-token",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 502
    assert response.json["error"] == "Remote organization_show failed"
def test_unmocked_requests_are_blocked():
    with pytest.raises(AssertionError):
        requests.post("https://data.uni-hannover.de/api/3/action/package_create")


@pytest.mark.parametrize("status_code", [401, 403, 404, 500])
def test_remote_api_http_errors_are_sanitized(monkeypatch, status_code):
    from ckanext.dataset_transfer.controllers import base

    original_get = requests.get

    def fake_get(url, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, **kwargs)
        return FakeResponse(
            status_code,
            {
                "success": False,
                "error": {"message": "Destination rejected the request"},
            },
        )

    monkeypatch.setattr(
        base.requests,
        "get",
        fake_get,
    )

    with pytest.raises(base.RemoteAPIError) as raised:
        base.BaseController._remote_json(
            "get", "organization_show", headers={"Authorization": "secret-token"}
        )

    assert raised.value.status == status_code
    assert "secret-token" not in str(raised.value)
    expected = {
        401: "authentication failed",
        403: "authorization failed",
        404: "was not found",
        500: "internal server error",
    }
    assert expected[status_code] in str(raised.value)


@pytest.mark.parametrize(
    "failure,response,message",
    [
        (requests.ConnectionError("secret-token"), None, "connection failed"),
        (requests.Timeout("secret-token"), None, "timed out"),
        (None, InvalidJSONResponse(200), "invalid JSON"),
        (None, FakeResponse(200, ["unexpected"]), "unexpected response structure"),
    ],
)
def test_remote_api_transport_and_response_errors_are_clear_and_sanitized(
    monkeypatch, failure, response, message
):
    from ckanext.dataset_transfer.controllers import base

    original_get = requests.get

    def fake_get(url, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, **kwargs)
        if failure:
            raise failure
        return response

    monkeypatch.setattr(base.requests, "get", fake_get)

    with pytest.raises(base.RemoteAPIError) as raised:
        base.BaseController._remote_json(
            "get", "organization_show", headers={"Authorization": "secret-token"}
        )

    assert message in str(raised.value)
    assert "secret-token" not in str(raised.value)


@pytest.mark.parametrize(
    "failure_mode,expected_operation,expected_status",
    [
        ("resource_create_403", "resource_create", 403),
        ("resource_create_500", "resource_create", 500),
        ("resource_patch_500", "resource_patch", 500),
        ("missing_local_file", "local_file_read", None),
    ],
)
@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_resource_failure_keeps_incomplete_transfer_and_never_reports_success(
    app, monkeypatch, tmp_path, failure_mode, expected_operation, expected_status
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    user = factories.SysadminWithToken()
    upload_id = "abcdef1234567890abcdef1234567890"
    storage_path = tmp_path / "storage"
    if failure_mode == "resource_patch_500":
        upload_path = (
            storage_path / "resources" / upload_id[:3] / upload_id[3:6]
        )
        upload_path.mkdir(parents=True)
        (upload_path / upload_id[6:]).write_bytes(b"test upload")
    failing_resource = {
        "id": upload_id if failure_mode in ("resource_patch_500", "missing_local_file") else "url-failure",
        "name": "Failing resource",
        "url": "resource.dat",
        "url_type": "upload" if failure_mode in ("resource_patch_500", "missing_local_file") else "",
    }
    dataset = {
        "id": "resource-failure-dataset",
        "name": "resource-failure-dataset",
        "title": "Resource failure dataset",
        "notes": "Failure handling",
        "resources": [
            {
                "id": "successful-resource",
                "name": "Successful resource",
                "url": "https://example.test/success.csv",
                "url_type": "",
            },
            failing_resource,
        ],
        "groups": [],
    }
    original_get = requests.get
    resource_calls = [0]

    monkeypatch.setitem(toolkit.config, "ckan.storage_path", str(storage_path))
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "test-organization",
    )
    monkeypatch.setattr(base.Helper, "check_access_edit_package", lambda _: True)
    monkeypatch.setattr(
        base.toolkit,
        "get_action",
        lambda name: lambda context, data_dict: dataset,
    )

    def fake_get(url, headers=None, params=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, params=params, **kwargs)
        if url.endswith("/package_show"):
            return FakeResponse(
                404, {"success": False, "error": {"message": "Not found"}}
            )
        return FakeResponse(
            200, {"success": True, "result": {"id": "target-org-id"}}
        )

    def fake_post(url, **kwargs):
        if url.endswith("/package_create"):
            assert "id" not in kwargs["json"]
            return FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "id": "remote-dataset-id",
                        "name": "remote-dataset",
                    },
                },
            )
        if url.endswith("/resource_create"):
            resource_calls[0] += 1
            if resource_calls[0] == 2 and failure_mode.startswith("resource_create"):
                status = int(failure_mode.rsplit("_", 1)[1])
                return FakeResponse(
                    status,
                    {"success": False, "error": {"message": "Resource rejected"}},
                )
            return FakeResponse(
                200,
                {"success": True, "result": {"id": "remote-resource-id"}},
            )
        if url.endswith("/resource_patch"):
            return FakeResponse(
                500,
                {"success": False, "error": {"message": "Upload rejected"}},
            )
        pytest.fail("Unexpected destination request: {}".format(url))

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base.requests, "post", fake_post)

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "api_token": "test-token",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 502
    assert response.json["success"] is False
    assert response.json["error"] == "Resource transfer incomplete"
    failure = response.json["resource_failures"][0]
    assert failure["operation"] == expected_operation
    if expected_status:
        assert failure["status"] == expected_status
    incomplete = PublishedDataset.get_incomplete_luh_transfer(dataset["id"])
    assert incomplete
    assert PublishedDataset.get_by_dataset_and_target(dataset["id"], "luh") is None

    retry = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "api_token": "test-token",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )
    assert retry.status_code == 409
    assert retry.json["error"] == "Incomplete transfer requires reconciliation"


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_repeated_publish_after_success_is_rejected_before_remote_calls(
    app, monkeypatch
):
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset
    from datetime import datetime

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    original_get = requests.get
    PublishedDataset(
        dataset_id=dataset["id"],
        doi="10.123/existing",
        published_url="https://destination.example/dataset/existing",
        published_dataset_id=PublishedDataset.encode_target_id(
            "luh", "existing-remote-id"
        ),
        publish_time=datetime.utcnow(),
    ).save()
    monkeypatch.setattr(base.Helper, "check_access_edit_package", lambda _: True)
    def fail_remote_get(url, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, **kwargs)
        pytest.fail("Remote API must not be called")

    monkeypatch.setattr(base.requests, "get", fail_remote_get)

    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 409
    assert response.json["error"] == "Already transferred"
    assert response.json["existing_transfer"]["published_dataset_id"] == (
        "existing-remote-id"
    )


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_remote_dataset_is_reconciled_when_initial_local_save_failed(
    app, monkeypatch
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    user = factories.SysadminWithToken()
    dataset = factories.Dataset(resources=[])
    original_get = requests.get
    destination_exists = [False]
    package_create_calls = [0]

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "test-organization",
    )
    monkeypatch.setattr(base.Helper, "check_access_edit_package", lambda _: True)

    def fake_get(url, headers=None, params=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, params=params, **kwargs)
        if url.endswith("/package_show"):
            if destination_exists[0]:
                return FakeResponse(
                    200,
                    {
                        "success": True,
                        "result": {
                            "id": "orphaned-remote-id",
                            "name": dataset["name"],
                        },
                    },
                )
            return FakeResponse(
                404, {"success": False, "error": {"message": "Not found"}}
            )
        return FakeResponse(
            200, {"success": True, "result": {"id": "target-org-id"}}
        )

    def fake_post(url, **kwargs):
        assert url.endswith("/package_create")
        package_create_calls[0] += 1
        destination_exists[0] = True
        return FakeResponse(
            200,
            {
                "success": True,
                "result": {
                    "id": "orphaned-remote-id",
                    "name": dataset["name"],
                },
            },
        )

    def fail_incomplete_save(self):
        raise RuntimeError("simulated local save failure")

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base.requests, "post", fake_post)
    monkeypatch.setattr(PublishedDataset, "save", fail_incomplete_save)
    params = {
        "package_id": dataset["id"],
        "api_token": "test-token",
        "terms_of_usage": "true",
        "rights_of_use": "true",
    }

    first = app.post(
        "/dataset_transfer/publish", params=params, headers=_auth_headers(user)
    )
    assert first.status_code == 500

    retry = app.post(
        "/dataset_transfer/publish", params=params, headers=_auth_headers(user)
    )
    assert retry.status_code == 409
    assert retry.json["error"] == "Destination dataset requires reconciliation"
    assert package_create_calls == [1]


@pytest.mark.usefixtures("clean_db")
def test_postgresql_publish_lock_blocks_a_concurrent_request():
    import ckan.model as model
    import sqlalchemy as sa

    first = model.Session.bind.connect()
    second = model.Session.bind.connect()
    first_transaction = first.begin()
    second_transaction = second.begin()
    try:
        first.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": "dataset-transfer:luh:concurrent-dataset"},
        )
        second.execute(sa.text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(sa.exc.DBAPIError):
            second.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": "dataset-transfer:luh:concurrent-dataset"},
            )
    finally:
        second_transaction.rollback()
        first_transaction.rollback()
        second.close()
        first.close()
