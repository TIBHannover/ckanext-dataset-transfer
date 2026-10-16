# encoding: utf-8

import io
import logging
import os
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)
LOG_BODY_LIMIT = 2000

DEFAULT_RADAR_DATASET_XSD = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "radar"
    / "v9.3"
    / "RadarDataset.xsd"
)

RADAR_DATASET_NS = "http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset"
RADAR_ELEMENTS_NS = "http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = (
    "http://radar-service.eu/schemas/descriptive/radar/v09/radar-elements "
    "https://www.radar-service.eu/schemas/descriptive/radar/v9.3/RadarElements.xsd "
    "http://radar-service.eu/schemas/descriptive/radar/v09/radar-dataset "
    "https://www.radar-service.eu/schemas/descriptive/radar/v9.3/RadarDataset.xsd "
)

ET.register_namespace("", RADAR_ELEMENTS_NS)
ET.register_namespace("rd", RADAR_DATASET_NS)
ET.register_namespace("xsi", XSI_NS)


class RadarConfigError(Exception):
    pass


class RadarPublishError(Exception):
    pass


class RadarPublisher(object):
    def __init__(self, config=None, request_session=None):
        self.config = config or toolkit.config
        self.requests = request_session or requests
        self.context_url = self._required("ckanext.dataset_transfer.radar.context_url").rstrip("/")
        self.workspace_id = self._required("ckanext.dataset_transfer.radar.workspace_id")
        self.schema_key = self.config.get("ckanext.dataset_transfer.radar.schema_key", "RDDM")
        self.schema_version = self.config.get("ckanext.dataset_transfer.radar.schema_version", "9.3")
        self.responsible_email = self._required(
            "ckanext.dataset_transfer.radar.responsible_email"
        )
        self.retention_period = int(
            self.config.get("ckanext.dataset_transfer.radar.retention_period", 10)
        )
        self.dataset_url_template = self.config.get(
            "ckanext.dataset_transfer.radar.dataset_url_template",
            self.context_url + "/datasets/{dataset_id}",
        )
        self.ingest_url = self.config.get(
            "ckanext.dataset_transfer.radar.ingest_url",
            self.context_url.replace("/radar", "") + "/radar-ingest",
        ).rstrip("/")
        self.descriptive_xsd_path = self.config.get(
            "ckanext.dataset_transfer.radar.descriptive_xsd_path",
            str(DEFAULT_RADAR_DATASET_XSD),
        )
        self.metadata_identifier_prefix = self.config.get(
            "ckanext.dataset_transfer.radar.metadata_identifier_prefix",
            "10.0000",
        )
        self.publisher = self.config.get(
            "ckanext.dataset_transfer.radar.publisher",
            "TIB",
        )
        self.default_subject_area = self.config.get(
            "ckanext.dataset_transfer.radar.default_subject_area",
            "Other",
        )
        self.default_rights = self.config.get(
            "ckanext.dataset_transfer.radar.default_rights",
            "Other",
        )

    def _required(self, key):
        value = self.config.get(key)
        if value:
            return value
        raise RadarConfigError("Missing CKAN config value: {}".format(key))

    def _access_token(self):
        configured_token = self.config.get("ckanext.dataset_transfer.radar.access_token")
        if configured_token:
            log.info("RADAR publish using configured access token")
            return configured_token

        token_url = self.context_url + "/api/tokens"
        log.info("RADAR token request started url=%s", token_url)
        token_payload = {
            "clientId": self._required("ckanext.dataset_transfer.radar.client_id"),
            "clientSecret": self._required("ckanext.dataset_transfer.radar.client_secret"),
            "redirectUrl": self._required("ckanext.dataset_transfer.radar.redirect_url"),
            "userName": self._required("ckanext.dataset_transfer.radar.user_name"),
            "userPassword": self._required("ckanext.dataset_transfer.radar.user_password"),
        }
        try:
            response = self.requests.post(token_url, json=token_payload, timeout=60)
        except requests.RequestException as error:
            log.exception("RADAR token request failed url=%s", token_url)
            raise RadarPublishError("RADAR token request failed: {}".format(error))
        # Token response bodies contain credentials and must never be logged.
        log.info(
            "RADAR token response status=%s url=%s",
            getattr(response, "status_code", ""),
            getattr(response, "url", ""),
        )
        self._raise_for_radar(response, "RADAR token request failed")
        try:
            token_json = response.json()
        except ValueError as error:
            raise RadarPublishError("RADAR token response was not valid JSON") from error
        if not token_json.get("access_token"):
            raise RadarPublishError("RADAR token response did not contain access_token")
        return token_json["access_token"]

    def publish_dataset(self, dataset):
        log.info(
            "RADAR publish started package_id=%s package_name=%s resource_count=%s",
            dataset.get("id"),
            dataset.get("name"),
            len(dataset.get("resources") or []),
        )
        access_token = self._access_token()
        headers = {"Authorization": "Bearer {}".format(access_token)}

        created_dataset = self._create_dataset(dataset, headers)
        dataset_id = created_dataset["id"]

        metadata_xml = build_radar_metadata_xml(
            dataset,
            identifier_prefix=self.metadata_identifier_prefix,
            publisher=self.publisher,
            subject_area=self.default_subject_area,
            rights=self.default_rights,
        )
        log.info(
            "RADAR metadata XML generated package_id=%s bytes=%s xsd_path=%s",
            dataset.get("id"),
            len(metadata_xml),
            self.descriptive_xsd_path,
        )
        validate_radar_metadata_xml(metadata_xml, self.descriptive_xsd_path)
        log.info("RADAR local metadata validation passed package_id=%s", dataset.get("id"))
        self._upload_metadata(dataset_id, metadata_xml, headers)

        # RADAR removes the schema-valid placeholder identifier on upload. It must
        # assign its DOI before validating the stored descriptive metadata.
        doi = self._assign_doi(dataset_id, headers)
        self._validate_uploaded_metadata(dataset_id, headers)

        archive = build_resource_archive(dataset)
        if archive is not None:
            with zipfile.ZipFile(archive, "r") as zip_file:
                archive_entries = [
                    item.filename for item in zip_file.infolist() if not item.is_dir()
                ]
            archive.seek(0, os.SEEK_END)
            archive_size = archive.tell()
            archive.seek(0)
            log.info(
                "RADAR resource archive built package_id=%s dataset_id=%s bytes=%s entries=%s",
                dataset.get("id"),
                dataset_id,
                archive_size,
                archive_entries,
            )
            self._upload_archive(dataset_id, archive, headers)
            self._verify_uploaded_resources(dataset_id, archive_entries, headers)
        else:
            log.info(
                "RADAR resource archive skipped package_id=%s dataset_id=%s reason=no_resources",
                dataset.get("id"),
                dataset_id,
            )

        published_url = self.dataset_url_template.format(dataset_id=dataset_id)
        log.info(
            "RADAR publish completed package_id=%s dataset_id=%s doi=%s published_url=%s",
            dataset.get("id"),
            dataset_id,
            doi,
            published_url,
        )
        return {
            "success": True,
            "doi": doi,
            "published_url": published_url,
            "published_dataset_id": dataset_id,
        }

    def _create_dataset(self, dataset, headers):
        payload = {
            "id": None,
            "parentId": self.workspace_id,
            "state": "PENDING",
            "technicalMetadata": {
                "retentionPeriod": self.retention_period,
                "responsibleEmail": self.responsible_email,
                "publicationBacklink": _dataset_backlink(dataset),
                "schema": {
                    "key": self.schema_key,
                    "version": self.schema_version,
                },
            },
            "descriptiveMetadata": {
                "title": dataset.get("title") or dataset.get("name") or "CKAN dataset",
            },
        }
        url = self.context_url + "/api/workspaces/{}/datasets".format(self.workspace_id)
        log.info(
            "RADAR dataset create request package_id=%s workspace_id=%s url=%s",
            dataset.get("id"),
            self.workspace_id,
            url,
        )
        try:
            response = self.requests.post(
                url,
                headers=dict(headers, **{"Content-Type": "application/json"}),
                json=payload,
                timeout=120,
            )
        except requests.RequestException as error:
            log.exception("RADAR dataset create request failed package_id=%s url=%s", dataset.get("id"), url)
            raise RadarPublishError("RADAR dataset creation failed: {}".format(error))
        _log_response("RADAR dataset create response", response)
        self._raise_for_radar(response, "RADAR dataset creation failed")
        created = response.json()
        if not created.get("id"):
            log.error("RADAR dataset create response missing id body=%s", _response_text(response))
            raise RadarPublishError("RADAR did not return a dataset id")
        log.info(
            "RADAR dataset created package_id=%s dataset_id=%s",
            dataset.get("id"),
            created.get("id"),
        )
        return created

    def _upload_metadata(self, dataset_id, metadata_xml, headers):
        url = self.context_url + "/api/datasets/{}/metadata".format(dataset_id)
        log.info(
            "RADAR metadata upload request dataset_id=%s url=%s bytes=%s",
            dataset_id,
            url,
            len(metadata_xml),
        )
        try:
            response = self.requests.post(
                url,
                headers=headers,
                files={
                    "metadataFile": (
                        "radar-metadata.xml",
                        metadata_xml,
                        "application/xml",
                    )
                },
                timeout=120,
            )
        except requests.RequestException as error:
            log.exception("RADAR metadata upload request failed dataset_id=%s url=%s", dataset_id, url)
            raise RadarPublishError("RADAR metadata upload failed: {}".format(error))
        _log_response("RADAR metadata upload response", response)
        self._raise_for_radar(response, "RADAR metadata upload failed")
        log.info("RADAR metadata upload completed dataset_id=%s", dataset_id)

    def _assign_doi(self, dataset_id, headers):
        url = self.context_url + "/api/datasets/{}/doi".format(dataset_id)
        log.info("RADAR DOI assignment request dataset_id=%s url=%s", dataset_id, url)
        try:
            response = self.requests.post(url, headers=headers, timeout=120)
        except requests.RequestException as error:
            log.exception(
                "RADAR DOI assignment request failed dataset_id=%s url=%s",
                dataset_id,
                url,
            )
            raise RadarPublishError("RADAR DOI assignment failed: {}".format(error))
        _log_response("RADAR DOI assignment response", response)
        self._raise_for_radar(response, "RADAR DOI assignment failed")

        doi = _doi_from_response(response)
        if not _looks_like_doi(doi):
            # Some RADAR versions return an empty success body; retrieve the DOI
            # after the successful assignment rather than inventing one locally.
            doi = self._read_doi(dataset_id, headers)
        log.info("RADAR DOI assignment completed dataset_id=%s doi=%s", dataset_id, doi)
        return doi

    def _validate_uploaded_metadata(self, dataset_id, headers):
        url = self.context_url + "/api/datasets/{}/metadata/validate".format(dataset_id)
        log.info("RADAR metadata validation request dataset_id=%s url=%s", dataset_id, url)
        try:
            response = self.requests.get(url, headers=headers, timeout=120)
        except requests.RequestException as error:
            log.exception("RADAR metadata validation request failed dataset_id=%s url=%s", dataset_id, url)
            raise RadarPublishError("RADAR metadata validation failed: {}".format(error))
        _log_response("RADAR metadata validation response", response)
        self._raise_for_radar(response, "RADAR metadata validation failed")
        try:
            validation_json = response.json()
        except ValueError as error:
            raise RadarPublishError(
                "RADAR metadata validation returned an invalid response"
            ) from error
        validation_failed = (
            not isinstance(validation_json, dict)
            or validation_json.get("success") is False
            or validation_json.get("valid") is False
        )
        validation_succeeded = isinstance(validation_json, dict) and (
            validation_json.get("success") is True
            or validation_json.get("valid") is True
        )
        if validation_failed or not validation_succeeded:
            log.error(
                "RADAR metadata validation failed dataset_id=%s result=%s",
                dataset_id,
                validation_json,
            )
            raise RadarPublishError(
                "RADAR metadata validation failed: {}".format(validation_json)
            )
        log.info("RADAR metadata validation passed dataset_id=%s result=%s", dataset_id, validation_json)

    def _upload_archive(self, dataset_id, archive, headers):
        url = self.ingest_url + "/upload/{}/ingest".format(dataset_id)
        log.info("RADAR ingest upload request dataset_id=%s url=%s", dataset_id, url)
        try:
            response = self.requests.post(
                url,
                headers=headers,
                files={"file": ("ckan-resources.zip", archive, "application/zip")},
                timeout=1800,
            )
        except requests.RequestException as error:
            log.exception("RADAR ingest upload request failed dataset_id=%s url=%s", dataset_id, url)
            raise RadarPublishError("RADAR content ingest failed: {}".format(error))
        _log_response("RADAR ingest upload response", response)
        self._raise_for_radar(response, "RADAR content ingest failed")
        log.info("RADAR ingest upload completed dataset_id=%s", dataset_id)

    def _verify_uploaded_resources(self, dataset_id, expected_names, headers):
        url = self.context_url + "/api/datasets/{}/children".format(dataset_id)
        rows = 100
        offset = 0
        children = []
        total_hits = None
        log.info(
            "RADAR resource verification started dataset_id=%s expected_count=%s",
            dataset_id,
            len(expected_names),
        )

        while total_hits is None or offset < total_hits:
            try:
                response = self.requests.get(
                    url,
                    headers=headers,
                    params={"offset": offset, "rows": rows},
                    timeout=120,
                )
            except requests.RequestException as error:
                log.exception(
                    "RADAR resource verification request failed dataset_id=%s url=%s offset=%s",
                    dataset_id,
                    url,
                    offset,
                )
                raise RadarPublishError(
                    "RADAR resource verification failed: {}".format(error)
                )
            _log_response("RADAR children response", response)
            self._raise_for_radar(response, "RADAR resource verification failed")
            try:
                result = response.json()
            except ValueError as error:
                raise RadarPublishError(
                    "RADAR resource verification returned an invalid response"
                ) from error
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise RadarPublishError(
                    "RADAR resource verification response did not contain a data list"
                )

            page = result["data"]
            children.extend(page)
            try:
                total_hits = int(result.get("totalHits", len(children)))
            except (TypeError, ValueError) as error:
                raise RadarPublishError(
                    "RADAR resource verification returned an invalid totalHits value"
                ) from error
            offset += len(page)
            if not page and offset < total_hits:
                raise RadarPublishError(
                    "RADAR resource verification pagination ended before all children were returned"
                )

        actual_names = [
            child.get("fileName")
            for child in children
            if isinstance(child, dict) and child.get("fileName")
        ]
        expected = Counter(expected_names)
        actual = Counter(actual_names)
        missing = list((expected - actual).elements())
        if missing or len(actual_names) != len(expected_names):
            log.error(
                "RADAR resource verification failed dataset_id=%s expected=%s actual=%s missing=%s",
                dataset_id,
                expected_names,
                actual_names,
                missing,
            )
            raise RadarPublishError(
                "RADAR resource verification failed: expected {} files, found {}; "
                "missing archive entries: {}".format(
                    len(expected_names),
                    len(actual_names),
                    ", ".join(missing) or "none",
                )
            )
        log.info(
            "RADAR resource verification passed dataset_id=%s count=%s files=%s",
            dataset_id,
            len(actual_names),
            actual_names,
        )

    def _read_doi(self, dataset_id, headers):
        url = self.context_url + "/api/datasets/{}/doi".format(dataset_id)
        log.info("RADAR DOI lookup request dataset_id=%s url=%s", dataset_id, url)
        try:
            response = self.requests.get(url, headers=headers, timeout=120)
        except requests.RequestException as error:
            log.exception("RADAR DOI lookup request failed dataset_id=%s url=%s", dataset_id, url)
            raise RadarPublishError("RADAR DOI lookup failed: {}".format(error))
        _log_response("RADAR DOI lookup response", response)
        self._raise_for_radar(response, "RADAR DOI lookup failed")
        doi = _doi_from_response(response)
        if not _looks_like_doi(doi):
            raise RadarPublishError("RADAR DOI lookup did not return a DOI")
        return doi

    def _raise_for_radar(self, response, message):
        if 200 <= response.status_code < 300:
            return
        log.error(
            "%s status=%s url=%s body=%s",
            message,
            response.status_code,
            getattr(response, "url", ""),
            _response_text(response),
        )
        raise RadarPublishError(
            "{}: HTTP {} {}".format(message, response.status_code, _response_text(response))
        )


def build_radar_metadata_xml(
    dataset,
    identifier_prefix="10.0000",
    publisher="TIB",
    subject_area="Other",
    rights="Other",
):
    root = ET.Element(
        _dataset_tag("radarDataset"),
        {"{{{}}}schemaLocation".format(XSI_NS): SCHEMA_LOCATION},
    )
    identifier = ET.SubElement(root, _element_tag("identifier"), {"identifierType": "DOI"})
    identifier.text = _metadata_identifier(dataset, identifier_prefix)

    author = dataset.get("author") or dataset.get("creator") or dataset.get("maintainer")
    author = author or publisher or "Unknown"
    if author:
        creators = ET.SubElement(root, _element_tag("creators"))
        creator = ET.SubElement(creators, _element_tag("creator"))
        ET.SubElement(creator, _element_tag("creatorName")).text = author

    maintainer = dataset.get("maintainer")
    if maintainer:
        contributors = ET.SubElement(root, _element_tag("contributors"))
        contributor = ET.SubElement(
            contributors,
            _element_tag("contributor"),
            {"contributorType": "ContactPerson"},
        )
        if maintainer:
            ET.SubElement(contributor, _element_tag("contributorName")).text = maintainer

    ET.SubElement(root, _element_tag("title")).text = (
        dataset.get("title") or dataset.get("name") or "CKAN dataset"
    )

    notes = dataset.get("notes")
    if notes:
        descriptions = ET.SubElement(root, _element_tag("descriptions"))
        description = ET.SubElement(
            descriptions,
            _element_tag("description"),
            {"descriptionType": "Abstract"},
        )
        description.text = notes

    tags = dataset.get("tags") or []
    if tags:
        keywords = ET.SubElement(root, _element_tag("keywords"))
        for tag in tags:
            name = tag.get("display_name") or tag.get("name")
            if name:
                ET.SubElement(keywords, _element_tag("keyword"), {"keywordScheme": "Other"}).text = name

    publishers = ET.SubElement(root, _element_tag("publishers"))
    ET.SubElement(publishers, _element_tag("publisher")).text = publisher or "TIB"

    ET.SubElement(root, _element_tag("productionYear")).text = _production_year(dataset)
    language = _language(dataset)
    if language:
        ET.SubElement(root, _element_tag("language")).text = language

    subject_areas = ET.SubElement(root, _element_tag("subjectAreas"))
    subject_area_node = ET.SubElement(subject_areas, _element_tag("subjectArea"))
    ET.SubElement(subject_area_node, _element_tag("controlledSubjectAreaName")).text = (
        subject_area or "Other"
    )

    resource = ET.SubElement(root, _element_tag("resource"), {"resourceType": "Dataset"})
    resource.text = dataset.get("title") or dataset.get("name") or "CKAN dataset"

    rights_node = ET.SubElement(root, _element_tag("rights"))
    ET.SubElement(rights_node, _element_tag("controlledRights")).text = rights or "Other"

    rights_holders = ET.SubElement(root, _element_tag("rightsHolders"))
    ET.SubElement(rights_holders, _element_tag("rightsHolder")).text = (
        dataset.get("organization", {}).get("title")
        if isinstance(dataset.get("organization"), dict)
        else None
    ) or publisher or author

    xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_body


def validate_radar_metadata_xml(metadata_xml, xsd_path=None):
    log.info("RADAR local metadata validation started xsd_path=%s", xsd_path)
    ET.fromstring(metadata_xml)
    if not xsd_path:
        return
    if not os.path.exists(xsd_path):
        raise RadarConfigError(
            "Configured RADAR descriptive XSD does not exist: {}".format(xsd_path)
        )
    try:
        from lxml import etree
    except ImportError:
        raise RadarConfigError(
            "lxml is required for local RADAR XSD validation when descriptive_xsd_path is set"
        )
    try:
        schema = etree.XMLSchema(etree.parse(xsd_path))
    except etree.XMLSchemaParseError as error:
        raise RadarConfigError(
            "Configured RADAR descriptive XSD could not be loaded. "
            "RadarDataset.xsd imports RadarElements.xsd, which imports RadarTypes.xsd; "
            "keep these RADAR v9.3 XSD files in the same directory or use RADAR "
            "server-side validation only. Details: {}".format(error)
        )
    document = etree.fromstring(metadata_xml)
    if not schema.validate(document):
        log.error("RADAR local metadata validation failed errors=%s", schema.error_log)
        raise RadarPublishError(
            "Generated RADAR metadata XML is invalid: {}".format(schema.error_log)
        )
    log.info("RADAR local metadata validation completed xsd_path=%s", xsd_path)


def _response_text(response):
    text = getattr(response, "text", "") or ""
    return text[:LOG_BODY_LIMIT]


def _doi_from_response(response):
    try:
        body = response.json()
    except ValueError:
        return (getattr(response, "text", "") or "").strip()
    if isinstance(body, dict):
        return str(body.get("doi") or body.get("identifier") or "").strip()
    if isinstance(body, str):
        return body.strip()
    return ""


def _looks_like_doi(value):
    return bool(value and value.startswith("10.") and "/" in value)


def _log_response(message, response):
    log.info(
        "%s status=%s url=%s body=%s",
        message,
        getattr(response, "status_code", ""),
        getattr(response, "url", ""),
        _response_text(response),
    )


def build_resource_archive(dataset):
    resources = dataset.get("resources") or []
    if not resources:
        return None

    storage_path = toolkit.config.get("ckan.storage_path")
    archive = io.BytesIO()
    wrote_anything = False
    remote_resources = []
    has_remote_resources = any(
        resource.get("url_type") != "upload" and resource.get("url")
        for resource in resources
    )
    used_names = {"remote-resources.txt"} if has_remote_resources else set()

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for resource in resources:
            if resource.get("url_type") == "upload":
                resource_path = _resource_file_path(storage_path, resource.get("id"))
                if not resource_path or not os.path.isfile(resource_path):
                    raise RadarPublishError(
                        "Uploaded CKAN resource file is missing: resource_id={} filename={}".format(
                            resource.get("id") or "unknown",
                            _archive_name(resource),
                        )
                    )
                archive_name = _unique_archive_name(_archive_name(resource), used_names)
                zip_file.write(resource_path, archive_name)
                wrote_anything = True
                continue
            if resource.get("url"):
                remote_resources.append(
                    "{}\t{}".format(resource.get("name") or resource.get("id"), resource["url"])
                )

        if remote_resources:
            zip_file.writestr("remote-resources.txt", "\n".join(remote_resources))
            wrote_anything = True

    if not wrote_anything:
        return None
    archive.seek(0)
    return archive


def _dataset_tag(name):
    return "{{{}}}{}".format(RADAR_DATASET_NS, name)


def _element_tag(name):
    return "{{{}}}{}".format(RADAR_ELEMENTS_NS, name)


def _metadata_identifier(dataset, identifier_prefix):
    # The v9.3 XSD requires a DOI-shaped identifier before RADAR has assigned
    # the real DOI. Keep this explicitly provisional and independent of CKAN IDs.
    return "{}/radar-pending-assignment".format(identifier_prefix.rstrip("/"))


def _production_year(dataset):
    for field in ("production_year", "publication_year", "year"):
        value = dataset.get(field)
        if value:
            return str(value)
    metadata_created = dataset.get("metadata_created")
    if metadata_created:
        return str(metadata_created)[:4]
    return "unknown"


def _language(dataset):
    value = dataset.get("language") or dataset.get("lang")
    if not value:
        return ""
    value = str(value).lower()
    mapping = {"en": "eng", "de": "deu"}
    return mapping.get(value, value)


def _resource_file_path(storage_path, resource_id):
    if not storage_path or not resource_id or len(resource_id) < 6:
        return None
    return os.path.join(
        storage_path,
        "resources",
        resource_id[0:3],
        resource_id[3:6],
        resource_id[6:],
    )


def _archive_name(resource):
    name = resource.get("name") or resource.get("url") or resource.get("id")
    return os.path.basename(name) or resource.get("id") or "resource"


def _unique_archive_name(name, used_names):
    candidate = name
    stem, extension = os.path.splitext(name)
    suffix = 2
    while candidate in used_names:
        candidate = "{}-{}{}".format(stem, suffix, extension)
        suffix += 1
    used_names.add(candidate)
    return candidate


def _dataset_backlink(dataset):
    site_url = toolkit.config.get("ckan.site_url", "").rstrip("/")
    if site_url and dataset.get("name"):
        return site_url + "/dataset/" + dataset["name"]
    return ""
