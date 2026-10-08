# encoding: utf-8

import io
import logging
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)

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
            return configured_token

        token_url = self.context_url + "/api/tokens"
        token_payload = {
            "clientId": self._required("ckanext.dataset_transfer.radar.client_id"),
            "clientSecret": self._required("ckanext.dataset_transfer.radar.client_secret"),
            "redirectUrl": self._required("ckanext.dataset_transfer.radar.redirect_url"),
            "userName": self._required("ckanext.dataset_transfer.radar.user_name"),
            "userPassword": self._required("ckanext.dataset_transfer.radar.user_password"),
        }
        response = self.requests.post(token_url, json=token_payload)
        self._raise_for_radar(response, "RADAR token request failed")
        token_json = response.json()
        if not token_json.get("access_token"):
            raise RadarPublishError("RADAR token response did not contain access_token")
        return token_json["access_token"]

    def publish_dataset(self, dataset):
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
        validate_radar_metadata_xml(metadata_xml, self.descriptive_xsd_path)
        self._upload_metadata(dataset_id, metadata_xml, headers)
        self._validate_uploaded_metadata(dataset_id, headers)

        archive = build_resource_archive(dataset)
        if archive is not None:
            self._upload_archive(dataset_id, archive, headers)

        doi = self._read_doi(dataset_id, headers)
        published_url = self.dataset_url_template.format(dataset_id=dataset_id)
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
        response = self.requests.post(
            self.context_url + "/api/workspaces/{}/datasets".format(self.workspace_id),
            headers=dict(headers, **{"Content-Type": "application/json"}),
            json=payload,
        )
        self._raise_for_radar(response, "RADAR dataset creation failed")
        created = response.json()
        if not created.get("id"):
            raise RadarPublishError("RADAR did not return a dataset id")
        return created

    def _upload_metadata(self, dataset_id, metadata_xml, headers):
        response = self.requests.post(
            self.context_url + "/api/datasets/{}/metadata".format(dataset_id),
            headers=headers,
            files={
                "metadataFile": (
                    "radar-metadata.xml",
                    metadata_xml,
                    "application/xml",
                )
            },
        )
        self._raise_for_radar(response, "RADAR metadata upload failed")

    def _validate_uploaded_metadata(self, dataset_id, headers):
        response = self.requests.get(
            self.context_url + "/api/datasets/{}/metadata/validate".format(dataset_id),
            headers=headers,
        )
        self._raise_for_radar(response, "RADAR metadata validation failed")
        try:
            validation_json = response.json()
        except ValueError:
            validation_json = {}
        if isinstance(validation_json, dict) and validation_json.get("valid") is False:
            raise RadarPublishError(
                "RADAR metadata validation failed: {}".format(validation_json)
            )

    def _upload_archive(self, dataset_id, archive, headers):
        response = self.requests.post(
            self.ingest_url + "/upload/{}/ingest".format(dataset_id),
            headers=headers,
            files={"file": ("ckan-resources.zip", archive, "application/zip")},
        )
        self._raise_for_radar(response, "RADAR content ingest failed")

    def _read_doi(self, dataset_id, headers):
        response = self.requests.get(
            self.context_url + "/api/datasets/{}/doi".format(dataset_id),
            headers=headers,
        )
        if response.status_code != 200:
            log.info(
                "RADAR DOI lookup skipped dataset_id=%s status=%s body=%s",
                dataset_id,
                response.status_code,
                response.text[:1000],
            )
            return ""
        try:
            doi_json = response.json()
        except ValueError:
            return response.text.strip()
        if isinstance(doi_json, dict):
            return doi_json.get("doi") or doi_json.get("identifier") or ""
        return ""

    def _raise_for_radar(self, response, message):
        if 200 <= response.status_code < 300:
            return
        raise RadarPublishError(
            "{}: HTTP {} {}".format(message, response.status_code, response.text[:1000])
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
        raise RadarPublishError(
            "Generated RADAR metadata XML is invalid: {}".format(schema.error_log)
        )


def build_resource_archive(dataset):
    resources = dataset.get("resources") or []
    if not resources:
        return None

    storage_path = toolkit.config.get("ckan.storage_path")
    archive = io.BytesIO()
    wrote_anything = False
    remote_resources = []

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for resource in resources:
            if resource.get("url_type") == "upload" and storage_path:
                resource_path = _resource_file_path(storage_path, resource.get("id"))
                if resource_path and os.path.exists(resource_path):
                    zip_file.write(resource_path, _archive_name(resource))
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
    for field in ("doi", "identifier"):
        value = dataset.get(field)
        if value and "/" in value:
            return value
    local_id = dataset.get("id") or dataset.get("name") or "ckan-dataset"
    return "{}/{}".format(identifier_prefix.rstrip("/"), local_id.replace("/", "-"))


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
    if not resource_id or len(resource_id) < 6:
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


def _dataset_backlink(dataset):
    site_url = toolkit.config.get("ckan.site_url", "").rstrip("/")
    if site_url and dataset.get("name"):
        return site_url + "/dataset/" + dataset["name"]
    return ""
