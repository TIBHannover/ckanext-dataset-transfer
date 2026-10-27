# encoding: utf-8

import io
import logging
import os
import time
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import ckan.plugins.toolkit as toolkit
from ckanext.dataset_transfer.services.radar_metadata_mapping import (
    apply_fixed_radar_metadata,
    fixed_radar_metadata_errors,
    map_ckan_to_radar,
    validate_radar_metadata,
)
from ckanext.dataset_transfer.services.radar_reference_mapping import (
    get_ckan_reference_descriptions,
)


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
    def __init__(self, message, status=None, dataset_id=None, doi=None, missing=None):
        super(RadarPublishError, self).__init__(message)
        self.status = status
        self.dataset_id = dataset_id
        self.doi = doi
        self.missing = missing or []


class RadarPublisher(object):
    def __init__(self, config=None, request_session=None):
        self.config = config or toolkit.config
        self.requests = request_session or requests
        self.context_url = self._required("ckanext.dataset_transfer.radar.context_url").rstrip("/")
        self.workspace_id = self._required("ckanext.dataset_transfer.radar.workspace_id")
        self.schema_key = self._setting("ckanext.dataset_transfer.radar.schema_key", "RDDM")
        self.schema_version = self._setting("ckanext.dataset_transfer.radar.schema_version", "9.3")
        self.responsible_email = self._required(
            "ckanext.dataset_transfer.radar.responsible_email"
        )
        self.retention_period = int(
            self._setting("ckanext.dataset_transfer.radar.retention_period", 10)
        )
        self.dataset_url_template = self._setting(
            "ckanext.dataset_transfer.radar.dataset_url_template",
            self.context_url + "/datasets/{dataset_id}",
        )
        self.ingest_url = self._setting(
            "ckanext.dataset_transfer.radar.ingest_url",
            self.context_url.replace("/radar", "") + "/radar-ingest",
        ).rstrip("/")
        self.descriptive_xsd_path = self._setting(
            "ckanext.dataset_transfer.radar.descriptive_xsd_path",
            str(DEFAULT_RADAR_DATASET_XSD),
        )
        self.metadata_identifier_prefix = self._setting(
            "ckanext.dataset_transfer.radar.metadata_identifier_prefix",
            "10.0000",
        )
        self.publisher = self._setting(
            "ckanext.dataset_transfer.radar.publisher",
            "TIB",
        )
        try:
            self.verification_retry_interval = float(
                self._setting(
                    "ckanext.dataset_transfer.radar.verification_retry_interval", 5
                )
            )
            self.verification_max_duration = float(
                self._setting(
                    "ckanext.dataset_transfer.radar.verification_max_duration", 120
                )
            )
        except (TypeError, ValueError) as error:
            raise RadarConfigError(
                "RADAR verification interval and duration must be numbers"
            ) from error
        if self.verification_retry_interval <= 0:
            raise RadarConfigError(
                "RADAR verification retry interval must be greater than zero"
            )
        if self.verification_max_duration < 0:
            raise RadarConfigError(
                "RADAR verification maximum duration must not be negative"
            )

    def _required(self, key):
        value = self._setting(key)

        if value:
            return value

        raise RadarConfigError(
            "Missing RADAR configuration: {}".format(key)
        )

    def _access_token(self):
        configured_token = self._setting("ckanext.dataset_transfer.radar.access_token")
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

    def publish_dataset(self, dataset, reviewed_metadata=None, transfer_state=None):
        log.info(
            "RADAR publish started package_id=%s package_name=%s resource_count=%s",
            dataset.get("id"),
            dataset.get("name"),
            len(dataset.get("resources") or []),
        )
        project_id = self.config.get("ckanext.crc.project.id") or os.environ.get(
            "CKANEXT__CRC__PROJECT__ID"
        )
        award_number = self.config.get(
            "ckanext.dataset_transfer.radar.dfg_award_number"
        ) or os.environ.get(
            "CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER"
        )
        metadata = reviewed_metadata or map_ckan_to_radar(
            dataset,
            self.publisher,
            project_id=project_id,
            dfg_award_number=award_number,
        )
        metadata = apply_fixed_radar_metadata(
            metadata,
            dataset,
            project_id=project_id,
            dfg_award_number=award_number,
            reference_descriptions=get_ckan_reference_descriptions(dataset),
        )
        validation = validate_radar_metadata(metadata)
        policy_errors = fixed_radar_metadata_errors(
            dataset, project_id, award_number
        )
        if policy_errors:
            validation["errors"].extend(policy_errors)
            validation["success"] = False
        if not validation["success"]:
            raise RadarPublishError(
                "RADAR metadata is incomplete: {}".format(
                    "; ".join(item["message"] for item in validation["errors"])
                )
            )
        metadata_xml = build_radar_metadata_xml(
            validation["metadata"],
            identifier_prefix=self.metadata_identifier_prefix,
        )
        validate_radar_metadata_xml(metadata_xml, self.descriptive_xsd_path)
        log.info("RADAR local metadata validation passed package_id=%s", dataset.get("id"))

        # Authentication and dataset creation intentionally happen only after all
        # local semantic and XSD validation has passed.
        access_token = self._access_token()
        headers = {"Authorization": "Bearer {}".format(access_token)}

        transfer_state = transfer_state or {}
        resume_status = transfer_state.get("status")
        dataset_id = transfer_state.get("published_dataset_id")
        doi = transfer_state.get("doi") or ""
        if dataset_id:
            log.info(
                "RADAR publish resuming package_id=%s dataset_id=%s status=%s",
                dataset.get("id"),
                dataset_id,
                resume_status,
            )
        else:
            created_dataset = self._create_dataset(dataset, headers)
            dataset_id = created_dataset["id"]
        log.info(
            "RADAR metadata XML generated package_id=%s bytes=%s xsd_path=%s",
            dataset.get("id"),
            len(metadata_xml),
            self.descriptive_xsd_path,
        )
        if resume_status not in (
            "resource_upload_failure",
            "resource_verification_pending",
            "resource_verification_failure",
        ):
            try:
                self._upload_metadata(dataset_id, metadata_xml, headers)

                # RADAR removes the schema-valid placeholder identifier on upload. It must
                # assign its DOI before validating the stored descriptive metadata.
                doi = self._assign_doi(dataset_id, headers)
                self._validate_uploaded_metadata(dataset_id, headers)
            except RadarPublishError as error:
                _add_transfer_context(
                    error, "metadata_upload_failure", dataset_id, doi
                )
                raise
        elif not doi:
            try:
                doi = self._read_doi(dataset_id, headers)
            except RadarPublishError as error:
                _add_transfer_context(error, resume_status, dataset_id, doi)
                raise

        try:
            archive = build_resource_archive(dataset)
        except RadarPublishError as error:
            _add_transfer_context(
                error, "resource_upload_failure", dataset_id, doi
            )
            raise
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
            if resume_status not in (
                "resource_verification_pending",
                "resource_verification_failure",
            ):
                try:
                    self._upload_archive(dataset_id, archive, headers)
                except RadarPublishError as error:
                    _add_transfer_context(
                        error, "resource_upload_failure", dataset_id, doi
                    )
                    raise
            try:
                self._verify_uploaded_resources(dataset_id, archive_entries, headers)
            except RadarPublishError as error:
                if not error.status:
                    error.status = "resource_verification_failure"
                _add_transfer_context(error, error.status, dataset_id, doi)
                raise
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
        expected = Counter(expected_names)
        started_at = time.monotonic()
        deadline = started_at + self.verification_max_duration
        attempt = 0
        log.info(
            "RADAR resource verification started dataset_id=%s expected_count=%s "
            "retry_interval=%s max_duration=%s",
            dataset_id,
            len(expected_names),
            self.verification_retry_interval,
            self.verification_max_duration,
        )
        while True:
            attempt += 1
            actual_names = self._read_uploaded_resource_names(
                dataset_id, url, headers, rows
            )
            actual = Counter(actual_names)
            missing = list((expected - actual).elements())
            elapsed = time.monotonic() - started_at
            log.info(
                "RADAR resource verification dataset_id=%s attempt=%s expected=%s "
                "actual=%s missing=%s retry_interval=%s duration=%.3f",
                dataset_id,
                attempt,
                len(expected_names),
                len(actual_names),
                missing,
                self.verification_retry_interval,
                elapsed,
            )
            if not missing:
                log.info(
                    "RADAR resource verification successful dataset_id=%s "
                    "attempt=%s expected=%s actual=%s duration=%.3f",
                    dataset_id,
                    attempt,
                    len(expected_names),
                    len(actual_names),
                    elapsed,
                )
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.error(
                    "RADAR resource verification timeout dataset_id=%s attempt=%s "
                    "expected=%s actual=%s missing=%s duration=%.3f",
                    dataset_id,
                    attempt,
                    len(expected_names),
                    len(actual_names),
                    missing,
                    elapsed,
                )
                raise RadarPublishError(
                    "RADAR resource verification timed out for dataset {} after "
                    "{:.3f} seconds: expected {} files, found {}; missing archive "
                    "entries: {}".format(
                        dataset_id,
                        elapsed,
                        len(expected_names),
                        len(actual_names),
                        ", ".join(missing),
                    ),
                    status="resource_verification_pending",
                    dataset_id=dataset_id,
                    missing=missing,
                )

            delay = min(self.verification_retry_interval, remaining)
            log.info(
                "RADAR resource verification retrying dataset_id=%s attempt=%s "
                "in=%s seconds",
                dataset_id,
                attempt,
                delay,
            )
            time.sleep(delay)

    def _read_uploaded_resource_names(self, dataset_id, url, headers, rows):
        offset = 0
        children = []
        total_hits = None
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
                    "RADAR resource verification failed for dataset {}: {}".format(
                        dataset_id, error
                    ),
                    status="resource_verification_failure",
                    dataset_id=dataset_id,
                )
            _log_response("RADAR children response", response)
            self._raise_for_radar(response, "RADAR resource verification failed")
            try:
                result = response.json()
            except ValueError as error:
                raise RadarPublishError(
                    "RADAR resource verification returned an invalid response for "
                    "dataset {}".format(dataset_id)
                ) from error
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise RadarPublishError(
                    "RADAR resource verification response for dataset {} did not "
                    "contain a data list".format(dataset_id)
                )

            page = result["data"]
            children.extend(page)
            try:
                total_hits = int(result.get("totalHits", len(children)))
            except (TypeError, ValueError) as error:
                raise RadarPublishError(
                    "RADAR resource verification returned an invalid totalHits value "
                    "for dataset {}".format(dataset_id)
                ) from error
            offset += len(page)
            if not page and offset < total_hits:
                raise RadarPublishError(
                    "RADAR resource verification pagination for dataset {} ended "
                    "before all children were returned".format(dataset_id)
                )

        return [
            name for name in (_radar_child_filename(child) for child in children)
            if name
        ]

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

    def _setting(self, key, default=None):
        """
        Read RADAR configuration from CKAN settings or Docker
        environment variables.
        """
        value = self.config.get(key)

        if value is not None and str(value).strip():
            return value

        env_key = key.upper().replace(".", "_")

        value = os.environ.get(env_key)

        if value is not None and value.strip():
            return value

        return default


def _add_transfer_context(error, status, dataset_id, doi):
    error.status = status
    error.dataset_id = dataset_id
    error.doi = doi or error.doi


def _radar_child_filename(child):
    """Return a RADAR file name while excluding collection/folder children."""
    if not isinstance(child, dict):
        return None
    child_type = str(
        child.get("type") or child.get("resourceType") or child.get("kind") or ""
    ).upper()
    if child_type in ("DIRECTORY", "FOLDER", "COLLECTION"):
        return None

    technical_metadata = child.get("technicalMetadata")
    if not isinstance(technical_metadata, dict):
        technical_metadata = {}
    name = (
        child.get("fileName")
        or technical_metadata.get("fileName")
        or child.get("filename")
        or child.get("name")
    )
    if not isinstance(name, str) or not name or name.endswith("/"):
        return None
    return name


def build_radar_metadata_xml(metadata, identifier_prefix=None, **legacy_options):
    validation = validate_radar_metadata(metadata)
    if not validation["success"]:
        raise RadarPublishError(
            "RADAR metadata is incomplete: {}".format(
                "; ".join(item["message"] for item in validation["errors"])
            )
        )
    data = validation["metadata"]
    root = ET.Element(
        _dataset_tag("radarDataset"),
        {"{{{}}}schemaLocation".format(XSI_NS): SCHEMA_LOCATION},
    )
    identifier = ET.SubElement(root, _element_tag("identifier"), {"identifierType": "RADAR"})
    identifier.text = "RADAR/pending-assignment"

    _append_identifier_list(root, "alternateIdentifiers", "alternateIdentifier", data["alternate_identifiers"], "alternateIdentifierType", "type")
    related_identifiers = _container(root, "relatedIdentifiers", data["related_identifiers"])
    if related_identifiers is not None:
        for item in data["related_identifiers"]:
            ET.SubElement(related_identifiers, _element_tag("relatedIdentifier"), {
                "relatedIdentifierType": item["identifier_type"], "relationType": item["relation_type"],
            }).text = item["value"]

    creators = ET.SubElement(root, _element_tag("creators"))
    for item in data["creators"]:
        creator = ET.SubElement(creators, _element_tag("creator"))
        _append_person(creator, item, "creator")

    if data["contributors"]:
        contributors = ET.SubElement(root, _element_tag("contributors"))
        for item in data["contributors"]:
            contributor = ET.SubElement(contributors, _element_tag("contributor"), {"contributorType": item["type"]})
            _append_person(contributor, item, "contributor")

    ET.SubElement(root, _element_tag("title")).text = data["title"]
    additional_titles = _container(root, "additionalTitles", data["additional_titles"])
    if additional_titles is not None:
        for item in data["additional_titles"]:
            ET.SubElement(additional_titles, _element_tag("additionalTitle"), {"additionalTitleType": item["type"]}).text = item["value"]
    if data["descriptions"]:
        descriptions = ET.SubElement(root, _element_tag("descriptions"))
        for item in data["descriptions"]:
            ET.SubElement(descriptions, _element_tag("description"), {"descriptionType": item.get("type") or "Abstract"}).text = item["value"]
    if data["keywords"]:
        keywords = ET.SubElement(root, _element_tag("keywords"))
        for item in data["keywords"]:
            attributes = _attributes(item, (("scheme", "keywordScheme"), ("scheme_uri", "schemeURI"), ("value_uri", "valueURI"), ("classification_code", "classificationCode"), ("ontology_uri", "ontologyURI"), ("ontology_id", "ontologyId")))
            ET.SubElement(keywords, _element_tag("keyword"), attributes).text = item["value"]

    publishers = ET.SubElement(root, _element_tag("publishers"))
    for publisher in data["publishers"]:
        attributes = _attributes(
            publisher,
            (
                ("name_identifier_scheme", "nameIdentifierScheme"),
                ("scheme_uri", "schemeURI"),
                ("name_identifier", "nameIdentifier"),
            ),
        )
        ET.SubElement(
            publishers,
            _element_tag("publisher"),
            attributes,
        ).text = publisher["name"]
    ET.SubElement(root, _element_tag("productionYear")).text = data["production_year"]
    if data["publication_year"]:
        ET.SubElement(root, _element_tag("publicationYear")).text = data["publication_year"]
    if data["language"]:
        ET.SubElement(root, _element_tag("language")).text = data["language"]

    subject_areas = ET.SubElement(root, _element_tag("subjectAreas"))
    for item in data["subject_areas"]:
        controlled = item.get("controlled") if isinstance(item, dict) else item
        additional = item.get("additional") if isinstance(item, dict) else ""
        node = ET.SubElement(subject_areas, _element_tag("subjectArea"))
        ET.SubElement(node, _element_tag("controlledSubjectAreaName")).text = controlled
        if additional:
            ET.SubElement(node, _element_tag("additionalSubjectAreaName")).text = additional

    resource = ET.SubElement(root, _element_tag("resource"), {"resourceType": data["resource_type"]})
    resource.text = data["resource"]
    _append_simple_typed_list(root, "dataSources", "dataSource", data["data_sources"], "dataSourceDetail")
    _append_software(root, data["software"])
    _append_text_list(root, "processing", "dataProcessing", data["data_processing"])

    rights_node = ET.SubElement(root, _element_tag("rights"))
    ET.SubElement(rights_node, _element_tag("controlledRights")).text = data["rights"]
    if data["additional_rights"]:
        ET.SubElement(rights_node, _element_tag("additionalRights")).text = data["additional_rights"]

    rights_holders = ET.SubElement(root, _element_tag("rightsHolders"))
    for holder in data["rights_holders"]:
        attributes = _attributes(
            holder,
            (
                ("name_identifier_scheme", "nameIdentifierScheme"),
                ("scheme_uri", "schemeURI"),
                ("name_identifier", "nameIdentifier"),
            ),
        )
        ET.SubElement(
            rights_holders, _element_tag("rightsHolder"), attributes
        ).text = holder["name"]

    related_information = _container(root, "relatedInformations", data["related_information"])
    if related_information is not None:
        for item in data["related_information"]:
            attributes = {"relatedInformationType": item.get("type", "")} if item.get("type") else {}
            ET.SubElement(related_information, _element_tag("relatedInformation"), attributes).text = item["value"]
    _append_funding(root, data["funding_references"])
    if data["version"]:
        ET.SubElement(root, _element_tag("version")).text = data["version"]

    xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_body


def _container(root, name, values):
    return ET.SubElement(root, _element_tag(name)) if values else None


def _append_person(node, item, prefix):
    if (
        prefix in ("creator", "contributor")
        and item.get("creator_type") != "institution"
        and item.get("given_name")
        and item.get("family_name")
    ):
        name = "{}, {}".format(item["family_name"], item["given_name"])
    else:
        name = item.get("name") or ", ".join(
            part
            for part in (item.get("family_name"), item.get("given_name"))
            if part
        )
    ET.SubElement(node, _element_tag(prefix + "Name")).text = name
    # RADAR v9.3 has no creatorType attribute. The review-only type controls
    # whether person-specific name parts are emitted.
    if item.get("creator_type") != "institution" and item.get("given_name"):
        ET.SubElement(node, _element_tag("givenName")).text = item["given_name"]
    if item.get("creator_type") != "institution" and item.get("family_name"):
        ET.SubElement(node, _element_tag("familyName")).text = item["family_name"]
    if item.get("orcid"):
        ET.SubElement(node, _element_tag("nameIdentifier"), {"nameIdentifierScheme": "ORCID", "schemeURI": "https://orcid.org/"}).text = item["orcid"]
    if item.get("affiliation"):
        attributes = {}
        if item.get("affiliation_ror"):
            attributes = {"affiliationIdentifierScheme": "ROR", "schemeURI": "https://ror.org/", "affiliationIdentifier": item["affiliation_ror"]}
        ET.SubElement(node, _element_tag(prefix + "Affiliation"), attributes).text = item["affiliation"]


def _append_identifier_list(root, container_name, element_name, values, attribute_name, source_name):
    container = _container(root, container_name, values)
    if container is not None:
        for item in values:
            ET.SubElement(container, _element_tag(element_name), {attribute_name: item[source_name]}).text = item["value"]


def _append_simple_typed_list(root, container_name, element_name, values, attribute_name):
    container = _container(root, container_name, values)
    if container is not None:
        for item in values:
            ET.SubElement(container, _element_tag(element_name), {attribute_name: item["type"]}).text = item["value"]


def _append_text_list(root, container_name, element_name, values):
    container = _container(root, container_name, values)
    if container is not None:
        for value in values:
            ET.SubElement(container, _element_tag(element_name)).text = value.get("value") if isinstance(value, dict) else value


def _append_software(root, values):
    container = _container(root, "software", values)
    if container is None:
        return
    for item in values:
        software_type = ET.SubElement(container, _element_tag("softwareType"), {"type": item["type"]})
        ET.SubElement(software_type, _element_tag("softwareName"), {"softwareVersion": item["version"]}).text = item["name"]
        if item.get("alternative_name"):
            ET.SubElement(software_type, _element_tag("alternativeSoftwareName"), {"alternativeSoftwareVersion": item.get("alternative_version", "")}).text = item["alternative_name"]


def _append_funding(root, values):
    container = _container(root, "fundingReferences", values)
    if container is None:
        return
    for item in values:
        funding = ET.SubElement(container, _element_tag("fundingReference"))
        ET.SubElement(funding, _element_tag("funderName")).text = item["funder_name"]
        if item.get("funder_identifier"):
            attributes = {"type": item["funder_identifier_type"]}
            if item.get("funder_scheme_uri"):
                attributes["schemeURI"] = item["funder_scheme_uri"]
            ET.SubElement(funding, _element_tag("funderIdentifier"), attributes).text = item["funder_identifier"]
        for source, element in (("award_number", "awardNumber"), ("award_uri", "awardURI"), ("award_title", "awardTitle")):
            if item.get(source):
                ET.SubElement(funding, _element_tag(element)).text = item[source]


def _attributes(item, pairs):
    return {target: item[source] for source, target in pairs if item.get(source)}


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
