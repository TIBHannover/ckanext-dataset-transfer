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
    "organization",
    ["sfb_1153", "sfb_1368", "verified-trr375-luh-organization"],
)
def test_explicit_target_organization_is_used(monkeypatch, organization):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        " {} ".format(organization),
    )
    monkeypatch.setitem(toolkit.config, "ckan.root_path", "/sfb1153/ckan")

    assert Helper.get_organization_id() == organization


@pytest.mark.parametrize(
    "root_path,organization",
    [
        ("/sfb1153/ckan", "sfb_1153"),
        ("/sfb1368/ckan", "sfb_1368"),
        ("/sfb1153/{{LANG}}", "sfb_1153"),
        ("/sfb1368/{{LANG}}", "sfb_1368"),
        (" /sfb1368/{{LANG}}/ ", "sfb_1368"),
    ],
)
def test_legacy_target_organization_fallback_for_original_luh(
    monkeypatch, caplog, root_path, organization
):
    import logging
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.delitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        raising=False,
    )
    monkeypatch.delitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_api_url",
        raising=False,
    )
    monkeypatch.delitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_public_url",
        raising=False,
    )
    monkeypatch.setitem(toolkit.config, "ckan.root_path", root_path)

    with caplog.at_level(logging.WARNING):
        assert Helper.get_organization_id() == organization

    assert "deprecated ckan.root_path fallback" in caplog.text
    assert "target_organization" in caplog.text


def test_explicit_target_organization_overrides_legacy_mapping(monkeypatch):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "explicit-destination",
    )
    monkeypatch.setitem(toolkit.config, "ckan.root_path", "/sfb1153/ckan")
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_api_url",
        "https://custom.example/api/3/action/",
    )

    assert Helper.get_organization_id() == "explicit-destination"


@pytest.mark.parametrize(
    "root_path,api_url,public_url",
    [
        ("/unknown/ckan", None, None),
        ("/trr375/ckan", None, None),
        ("/trr375/{{LANG}}", None, None),
        ("/not-sfb1368/{{LANG}}", None, None),
        ("/sfb1368-other/{{LANG}}", None, None),
        ("/proxy/sfb1368/{{LANG}}", None, None),
        ("/sfb1368/unexpected", None, None),
        (
            "/sfb1153/ckan",
            "https://custom.example/api/3/action/",
            None,
        ),
        (
            "/sfb1368/ckan",
            None,
            "https://custom.example/",
        ),
    ],
)
def test_missing_target_organization_does_not_guess(
    monkeypatch, root_path, api_url, public_url
):
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.libs.helper import Helper

    monkeypatch.delitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        raising=False,
    )
    monkeypatch.setitem(toolkit.config, "ckan.root_path", root_path)
    for key, value in (
        ("ckanext.dataset_transfer.target_api_url", api_url),
        ("ckanext.dataset_transfer.target_public_url", public_url),
    ):
        if value is None:
            monkeypatch.delitem(toolkit.config, key, raising=False)
        else:
            monkeypatch.setitem(toolkit.config, key, value)

    assert Helper.get_organization_id() == ""


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
    assert not inspector.has_table("radar_oauth_token")
    assert not inspector.has_table("radar_oauth_state")


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
    assert "Migration test dataset" in _body(response)
    assert "Select a publish target" in _body(response)
    assert "LUH data repository" in _body(response)
    assert "RADAR4Ing" in _body(response)
    assert 'id="publish_target_details" hidden' in _body(response)
    assert "Connect to RADAR4Ing" not in _body(response)
    assert "RADAR4Ing authorization successful" not in _body(response)
    assert "Disconnect" not in _body(response)


@pytest.mark.parametrize(
    "path",
    [
        "/dataset_transfer/radar/login",
        "/dataset_transfer/radar/callback",
        "/dataset_transfer/radar/status",
        "/dataset_transfer/radar/disconnect",
    ],
)
def test_removed_radar_oauth_routes_are_not_available(app, path):
    response = app.get(path)
    assert response.status_code == 404


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_radar_metadata_review_renders_named_sections_and_preserves_fields(
    app, monkeypatch
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories

    user = factories.SysadminWithToken()
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.publisher",
        "Leibniz University Hannover",
    )
    monkeypatch.setitem(toolkit.config, "ckanext.crc.project.id", "TRR375")
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.radar.dfg_award_number",
        "511148852",
    )
    organization = factories.Organization(title="Leibniz University Hannover")
    dataset = factories.Dataset(
        title="RADAR review dataset",
        author="Ada Lovelace",
        maintainer="Grace Hopper",
        license_id="cc-by-4.0",
        tags=[{"name": "engineering"}],
        owner_org=organization["id"],
    )

    response = app.get(
        toolkit.url_for("dataset_transfer.publish_page", dataset_name=dataset["name"]),
        headers=_auth_headers(user),
    )
    body = _body(response)

    assert response.status_code == 200, body
    assert "Review RADAR4Ing Metadata" in body
    assert "They will not modify the original dataset" in body
    assert "Imported from CKAN; editable for RADAR only." not in body
    assert re.findall(r'data-radar-section="([^"]+)"', body) == [
        "dataset", "creators", "classification", "rights", "funding"
    ]
    assert 'data-radar-section="dataset" role="tabpanel">' in body
    for section in ("creators", "classification", "rights", "funding"):
        assert 'data-radar-section="{}" role="tabpanel" hidden'.format(section) in body
    assert 'value="DataManager" selected>Data Manager</option>' in body
    assert "Creators and Contributors" in body
    assert "Classification and Keywords" in body
    creators_section = body[
        body.index('id="radar_section_creators"'):
        body.index('id="radar_section_classification"')
    ]
    classification_section = body[
        body.index('id="radar_section_classification"'):
        body.index('id="radar_section_rights"')
    ]
    assert 'data-radar-list="creators"' in creators_section
    assert 'data-radar-list="contributors"' in creators_section
    assert 'data-radar-list="contributors"' not in classification_section
    assert 'data-radar-list="subject_areas"' in classification_section
    assert 'data-radar-list="keywords"' in classification_section
    assert '>Person</option>' in body
    assert "Person and affiliation" not in body
    assert 'class="form-control radar-affiliation radar-organization-search"' in body
    assert 'id="radar_rights_same_as_publisher"' in body
    assert 'class="radar-publisher-scheme-uri"' in body
    assert 'class="radar-rights-holder-scheme-uri"' in body
    assert 'class="radar-keyword-scheme" value="Other"' in body
    assert 'class="radar-value-uri"' in body
    assert 'class="radar-ontology-id"' in body
    assert 'class="fa fa-trash"' in body
    assert 'id="radar_rights" class="form-control"' in body
    assert body.count('<option value="CC BY 4.0 Attribution" selected>') == 1
    assert "Primary CRC Funding" in body
    assert "511148852" in body
    assert body.index('value="eng"') < body.index('value="deu"')
    assert body.index('value="deu"') < body.index("──────────")
    visible_text = re.sub(r"<[^>]+>", " ", body)
    assert not re.search(r"\bStep\s+\d+\b|\b[1-5]/5\b", visible_text)


def test_radar_review_javascript_preserves_submission_contract_and_dynamic_rows():
    source = (
        Path(__file__).parents[1] / "public" / "transfer.js"
    ).read_text(encoding="utf-8")
    template = (
        Path(__file__).parents[1]
        / "templates"
        / "snippets"
        / "radar_metadata_review.html"
    ).read_text(encoding="utf-8")
    publish_page = (
        Path(__file__).parents[1] / "templates" / "publish_page.html"
    ).read_text(encoding="utf-8")

    assert "let radarSectionOrder = ['dataset', 'creators', 'classification', 'rights', 'funding'];" in source
    assert "function show_radar_section(" in source
    assert "function collect_radar_metadata(" in source
    assert "function collect_person(" in source
    assert "function validate_radar_metadata_in_browser(" in source
    assert "function render_radar_confirmation(" in source
    assert "function add_radar_row(" in source
    assert "formdata.set('radar_metadata', JSON.stringify(collect_radar_metadata()));" in source
    assert "radar-keyword-scheme" in source
    assert "radar-value-uri" in source
    assert "radar-ontology-id" in source
    assert "contributors: 'creators'" in source
    assert "parse_ror_organization_results" in source
    assert "radar-organization-search" in source
    assert 'class="fa fa-trash"' in source
    assert "$('#radar_language').select2" in source
    assert "radar-connected" not in source
    assert "radar_oauth" not in source
    assert "Rights holder is the same as publisher" in template
    assert "<label>{{ _('Scheme URI') }}</label>" not in template
    assert publish_page.index("dataset_transfer_cancel_btn") < publish_page.index(
        "dataset_transfer_back_btn"
    ) < publish_page.index("dataset_transfer_next_btn")


def test_radar_controlled_licences_are_editable_and_validated():
    from ckanext.dataset_transfer.services.radar import build_radar_metadata_xml
    from ckanext.dataset_transfer.services.radar_metadata_mapping import (
        RIGHTS,
        apply_fixed_radar_metadata,
        map_ckan_to_radar,
        mapped_ckan_rights,
        validate_radar_metadata,
    )

    expected = (
        "CC BY 4.0 Attribution",
        "CC BY-ND 4.0 Attribution-NoDerivs",
        "CC BY-SA 4.0 Attribution-ShareAlike",
        "CC BY-NC 4.0 Attribution-NonCommercial",
        "CC BY-NC-SA 4.0 Attribution-NonCommercial-ShareAlike",
        "CC BY-NC-ND 4.0 Attribution-NonCommercial-NoDerivs",
        "CC0 1.0 Universal Public Domain Dedication",
        "Public Domain Mark 1.0",
        "Attribution License (ODC-By)",
        "Open Database License (ODC-ODbL)",
        "Public Domain Dedication and License (PDDL)",
        "Apache License 2.0",
        "Common Development and Distribution License 1.0",
        "Eclipse Public License 1.0",
        "Eclipse Public License 2.0",
        "GNU General Public License v3.0 only",
        "GNU Lesser General Public License v3.0 only",
        "BSD 2-Clause Simplified License",
        "BSD 3-Clause New or Revised License",
        "MIT License",
        "All rights reserved",
        "Other",
    )
    assert RIGHTS == expected
    assert mapped_ckan_rights({"license_id": "cc-by"}) == expected[0]
    assert mapped_ckan_rights({"license_id": "cc-by-sa"}) == expected[2]
    assert mapped_ckan_rights({"license_id": "cc-zero"}) == expected[6]
    assert mapped_ckan_rights({"license_id": "mit"}) == "MIT License"
    assert mapped_ckan_rights({"license_id": "notspecified"}) == ""

    dataset = {
        "id": "source-id",
        "name": "source-name",
        "title": "Licence test",
        "notes": "Description",
        "author": "Ada Lovelace",
        "license_id": "cc-by",
        "metadata_created": "2026-01-15T12:00:00",
        "organization": {"title": "Leibniz University Hannover"},
        "resources": [],
    }
    metadata = map_ckan_to_radar(
        dataset,
        project_id="TRR375",
        dfg_award_number="511148852",
    )
    assert metadata["rights"] == "CC BY 4.0 Attribution"
    metadata["rights"] = "MIT License"
    reviewed = apply_fixed_radar_metadata(
        metadata,
        dataset,
        project_id="TRR375",
        dfg_award_number="511148852",
    )
    validation = validate_radar_metadata(reviewed)
    assert validation["success"], validation["errors"]
    xml = build_radar_metadata_xml(validation["metadata"])
    assert b"<controlledRights>MIT License</controlledRights>" in xml
    assert dataset["license_id"] == "cc-by"

    reviewed["rights"] = "Unsupported licence"
    errors = validate_radar_metadata(reviewed)["errors"]
    assert any(error["field"] == "rights" for error in errors)


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_page_masks_stored_luh_token(app):
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    token = "never-render-this-complete-token-3f2a"
    PublishApiToken(
        api_token=token,
        user_id=user["id"],
        target_ckan="https://data.uni-hannover.de/",
    ).save()

    response = app.get(
        toolkit.url_for("dataset_transfer.publish_page", dataset_name=dataset["name"]),
        headers=_auth_headers(user),
    )
    body = _body(response)

    assert response.status_code == 200
    assert 'id="api_token_saved" value="saved" checked' in body
    assert "Stored token" in body
    assert "3f2a" in body
    assert token not in body


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_page_shows_recorded_radar_transfer_without_blocking_luh(app):
    from datetime import datetime
    import ckan.tests.factories as factories
    import ckan.plugins.toolkit as toolkit
    from ckanext.dataset_transfer.models.published_dataset import PublishedDataset

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    published_url = "https://radar.example.test/datasets/radar-id"
    PublishedDataset(
        dataset_id=dataset["id"],
        doi="10.123/radar",
        published_url=published_url,
        publish_time=datetime.utcnow(),
        published_dataset_id=PublishedDataset.encode_target_id("radar", "radar-id"),
    ).save()

    response = app.get(
        toolkit.url_for("dataset_transfer.publish_page", dataset_name=dataset["name"]),
        headers=_auth_headers(user),
    )
    body = _body(response)

    assert response.status_code == 200
    assert 'data-radar-transferred="true"' in body
    assert "This dataset is already in RADAR4Ing." in body
    assert published_url in body
    assert '<option value="luh">LUH data repository</option>' in body


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
def test_luh_publish_rejects_missing_new_token_after_consent(app, monkeypatch):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories

    user = factories.SysadminWithToken()
    dataset = factories.Dataset()
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "configured-destination",
    )
    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "publish_target": "luh",
            "api_token": "",
            "save_api_token_box": "false",
            "token_exist_box": "false",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 400
    assert response.json["error"] == "Invalid request"
    assert response.json["message"] == "A destination API token is required."


@pytest.mark.parametrize(
    "submitted_token,use_saved,save_new,expected_remote_token,expected_saved_token",
    [
        ("ignored-token", True, False, "stored-token", "stored-token"),
        ("temporary-token", False, False, "temporary-token", "stored-token"),
        ("replacement-token", False, True, "replacement-token", "replacement-token"),
    ],
    ids=("saved-token", "temporary-token", "replace-saved-token"),
)
@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_luh_token_choice_controls_remote_and_persisted_token(
    app,
    monkeypatch,
    submitted_token,
    use_saved,
    save_new,
    expected_remote_token,
    expected_saved_token,
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base
    from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken

    user = factories.SysadminWithToken()
    dataset = factories.Dataset(resources=[])
    PublishApiToken(
        api_token="stored-token",
        user_id=user["id"],
        target_ckan="https://data.uni-hannover.de/",
    ).save()
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "configured-destination",
    )
    monkeypatch.setattr(
        base.Helper, "check_access_edit_package", lambda package_id: True
    )
    remote_tokens = []

    def fake_remote_json(method, action, **kwargs):
        remote_tokens.append(kwargs["headers"]["Authorization"])
        if action == "organization_show":
            return {"success": True, "result": {"id": "target-org-id"}}
        if action == "package_show":
            raise base.RemoteAPIError(action, "not found", status=404)
        if action == "package_create":
            return {
                "success": True,
                "result": {
                    "id": "target-dataset-id",
                    "name": "target-dataset",
                    "doi": "10.123/test",
                },
            }
        pytest.fail("Unexpected remote action: {}".format(action))

    monkeypatch.setattr(base.BaseController, "_remote_json", fake_remote_json)
    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "publish_target": "luh",
            "api_token": submitted_token,
            "save_api_token_box": str(save_new).lower(),
            "token_exist_box": str(use_saved).lower(),
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 200, response.json
    assert remote_tokens
    assert set(remote_tokens) == {expected_remote_token}
    assert PublishApiToken.get_by_user(user["id"]).api_token == expected_saved_token


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
    monkeypatch.setitem(toolkit.config, "ckan.root_path", "/unknown/ckan")
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_api_url",
        "https://custom.example/api/3/action/",
    )
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_public_url",
        "https://custom.example/",
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
    assert "target_organization" in response.json["message"]


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


def test_destination_conflict_exposes_only_sanitized_validation_errors(monkeypatch):
    from ckanext.dataset_transfer.controllers import base

    monkeypatch.setattr(
        base.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            409,
            {
                "success": False,
                "error": {
                    "__type": "Validation Error",
                    "name": ["That URL is already in use."],
                    "title": ["Missing value"],
                    "api_token": ["destination-secret-token"],
                    "message": "The destination rejected the dataset.",
                },
            },
        ),
    )

    with pytest.raises(base.RemoteAPIError) as raised:
        base.BaseController._remote_json(
            "post",
            "package_create",
            headers={"Authorization": "source-secret-token"},
            json={"name": "conflicting-name"},
        )

    error = raised.value
    assert error.status == 409
    assert error.validation_errors == {
        "name": ["That URL is already in use."],
        "title": ["Missing value"],
    }
    assert "dataset name may already exist" in str(error)
    assert "name: That URL is already in use." in str(error)
    assert "source-secret-token" not in str(error)
    assert "destination-secret-token" not in str(error)


def test_luh_payload_drops_invalid_source_id_and_destination_managed_fields():
    from ckanext.dataset_transfer.controllers import base

    source = {
        "id": "not a valid destination dataset id",
        "name": "research-dataset",
        "title": "Research Dataset",
        "notes": "Metadata that must be preserved",
        "tags": [{"name": "research"}],
        "extras": [{"key": "discipline", "value": "engineering"}],
        "metadata_created": "2026-11-18T10:00:00",
        "metadata_modified": "2026-11-18T11:00:00",
        "creator_user_id": "source-user-id",
        "revision_id": "source-revision-id",
        "organization": {"id": "source-organization"},
        "state": "active",
        "resources": [{"id": "source-resource-id"}],
        "groups": [{"id": "source-group-id"}],
    }
    original = json.loads(json.dumps(source))

    prepared = base.BaseController._prepare_luh_dataset(
        source, "destination-organization"
    )

    assert "id" not in prepared
    for field in base.BaseController.destination_managed_package_fields:
        assert field not in prepared
    assert prepared["name"] == source["name"]
    assert prepared["title"] == source["title"]
    assert prepared["notes"] == source["notes"]
    assert prepared["tags"] == source["tags"]
    assert prepared["extras"] == source["extras"]
    assert prepared["owner_org"] == "destination-organization"
    assert prepared["resources"] == []
    assert prepared["groups"] == []
    assert source == original


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_luh_package_create_conflict_returns_destination_validation_details(
    app, monkeypatch
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    dataset = factories.Dataset(resources=[])
    original_get = requests.get
    monkeypatch.setitem(
        toolkit.config,
        "ckanext.dataset_transfer.target_organization",
        "destination-organization",
    )
    monkeypatch.setattr(base.Helper, "check_access_edit_package", lambda _: True)

    def fake_get(url, headers=None, params=None, **kwargs):
        if urlparse(url).hostname in {"solr", "localhost", "127.0.0.1", "ckan"}:
            return original_get(url, headers=headers, params=params, **kwargs)
        if url.endswith("/package_show"):
            return FakeResponse(
                404, {"success": False, "error": {"message": "Not found"}}
            )
        return FakeResponse(
            200, {"success": True, "result": {"id": "destination-org-id"}}
        )

    def fake_post(url, **kwargs):
        assert url.endswith("/package_create")
        assert "id" not in kwargs["json"]
        return FakeResponse(
            409,
            {
                "success": False,
                "error": {
                    "name": ["That URL is already in use."],
                    "notes": ["Destination validation rejected this field."],
                    "authorization": ["Bearer destination-secret"],
                },
            },
        )

    monkeypatch.setattr(base.requests, "get", fake_get)
    monkeypatch.setattr(base.requests, "post", fake_post)
    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "publish_target": "luh",
            "api_token": "source-secret-token",
            "token_exist_box": "false",
            "save_api_token_box": "false",
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 409
    assert response.json["error"] == "Remote package_create failed"
    assert response.json["destination_status"] == 409
    assert response.json["validation_errors"] == {
        "name": ["That URL is already in use."],
        "notes": ["Destination validation rejected this field."],
    }
    serialized = json.dumps(response.json)
    assert "source-secret-token" not in serialized
    assert "destination-secret" not in serialized


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


@pytest.mark.parametrize("publish_target", ["luh", "radar"])
@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_repeated_publish_after_success_is_rejected_per_target_before_remote_calls(
    app, monkeypatch, publish_target
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
            publish_target, "existing-remote-id"
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
            "publish_target": publish_target,
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


@pytest.mark.usefixtures("dataset_transfer_migrated_db")
def test_publish_dataset_to_radar_fails_closed_without_authentication(
    app, monkeypatch
):
    import ckan.plugins.toolkit as toolkit
    import ckan.tests.factories as factories
    from ckanext.dataset_transfer.controllers import base

    user = factories.SysadminWithToken()
    dataset = {
        "id": "local-radar-dataset-id",
        "name": "local-radar-dataset",
        "title": "Local RADAR Dataset",
        "notes": "Dataset to test RADAR publishing",
        "author": "Radar Author",
        "maintainer": "Radar Maintainer",
        "license_id": "cc-by-4.0",
        "metadata_created": "2026-01-15T12:00:00",
        "organization": {"title": "Leibniz University Hannover"},
        "tags": [{"name": "radar"}],
        "resources": [],
    }
    for key, value in (
        ("ckanext.dataset_transfer.radar.context_url", "https://test.radar-service.eu/radar"),
        ("ckanext.dataset_transfer.radar.workspace_id", "workspace-id"),
        ("ckanext.dataset_transfer.radar.responsible_email", "data@example.test"),
        ("ckanext.dataset_transfer.radar.publisher", "Leibniz University Hannover"),
        ("ckanext.crc.project.id", "TRR375"),
        ("ckanext.dataset_transfer.radar.dfg_award_number", "511148852"),
    ):
        monkeypatch.setitem(toolkit.config, key, value)
    monkeypatch.setattr(base.Helper, "check_access_edit_package", lambda package_id: True)
    monkeypatch.setattr(
        base.toolkit,
        "get_action",
        lambda name: (
            lambda context, data_dict: dataset
            if name == "package_show"
            else pytest.fail("Unexpected CKAN action: {}".format(name))
        ),
    )

    reviewed_metadata = base.map_ckan_to_radar(
        dataset,
        "Leibniz University Hannover",
        project_id="TRR375",
        dfg_award_number="511148852",
    )
    response = app.post(
        "/dataset_transfer/publish",
        params={
            "package_id": dataset["id"],
            "publish_target": "radar",
            "radar_metadata": json.dumps(reviewed_metadata),
            "terms_of_usage": "true",
            "rights_of_use": "true",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 503
    assert response.json["error"] == "RADAR authentication not configured"
    assert response.json["message"] == "RADAR authentication is not configured."


def test_radar_publisher_requires_explicit_server_side_authentication():
    from ckanext.dataset_transfer.services.radar import (
        RadarConfigError,
        RadarPublisher,
    )

    config = {
        "ckanext.dataset_transfer.radar.context_url": (
            "https://test.radar-service.eu/radar"
        ),
        "ckanext.dataset_transfer.radar.workspace_id": "workspace-id",
        "ckanext.dataset_transfer.radar.responsible_email": "data@example.test",
        # A legacy shared token must never be discovered implicitly.
        "ckanext.dataset_transfer.radar.access_token": "legacy-shared-token",
    }
    with pytest.raises(RadarConfigError, match="authentication is not configured"):
        RadarPublisher(config=config)

    class ExplicitTokenRequests(object):
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse(200, {"id": "remote-dataset-id"})

    requests_session = ExplicitTokenRequests()
    publisher = RadarPublisher(
        config=config,
        request_session=requests_session,
        access_token="explicit-server-side-token",
    )
    created = publisher._create_dataset({"id": "source-id", "title": "Dataset"})

    assert created["id"] == "remote-dataset-id"
    assert requests_session.calls[0][1]["headers"]["Authorization"] == (
        "Bearer explicit-server-side-token"
    )


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
