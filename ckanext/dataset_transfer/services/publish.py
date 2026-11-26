import copy
import os
from datetime import datetime

import ckan.plugins.toolkit as toolkit

from ckanext.dataset_transfer.libs.helper import Helper
from ckanext.dataset_transfer.models.published_dataset import PublishedDataset
from ckanext.dataset_transfer.services.radar import (
    DEFAULT_RADAR_DATASET_XSD, RadarConfigError, RadarPublishError, RadarPublisher,
    build_radar_metadata_xml, validate_radar_metadata_xml,
)
from ckanext.dataset_transfer.services.radar_auth import RadarAuthConfigError, RadarTokenProvider
from ckanext.dataset_transfer.services.radar_metadata_mapping import (
    apply_fixed_radar_metadata, fixed_radar_metadata_errors, map_ckan_to_radar,
    normalize_reviewed_metadata, validate_radar_metadata,
)
from ckanext.dataset_transfer.services.radar_reference_mapping import get_ckan_reference_descriptions


class PublishError(Exception):
    def __init__(self, kind, message, **details):
        super(PublishError, self).__init__(message)
        self.kind, self.message, self.details = kind, message, details

    def as_dict(self):
        result = {"publication": [self.message], "error_type": [self.kind]}
        if self.details:
            result["details"] = self.details
        return result


class PublishService(object):
    """Request-independent publication orchestration shared by UI and actions."""

    @staticmethod
    def _radar_metadata(dataset, reviewed_metadata=None):
        project_id = toolkit.config.get("ckanext.crc.project.id") or os.environ.get("CKANEXT__CRC__PROJECT__ID")
        award_number = toolkit.config.get("ckanext.dataset_transfer.radar.dfg_award_number") or os.environ.get("CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER")
        if reviewed_metadata is None:
            publisher = toolkit.config.get("ckanext.dataset_transfer.radar.publisher") or os.environ.get("CKANEXT_DATASET_TRANSFER_RADAR_PUBLISHER")
            metadata = map_ckan_to_radar(dataset, publisher, project_id=project_id,
                dfg_award_number=award_number,
                reference_descriptions=get_ckan_reference_descriptions(dataset))
        else:
            metadata = normalize_reviewed_metadata(reviewed_metadata)
        metadata = apply_fixed_radar_metadata(metadata, dataset, project_id=project_id,
            dfg_award_number=award_number,
            reference_descriptions=get_ckan_reference_descriptions(dataset))
        validation = validate_radar_metadata(metadata)
        validation["errors"].extend(fixed_radar_metadata_errors(dataset, project_id, award_number))
        validation["success"] = not validation["errors"]
        if validation["success"]:
            try:
                metadata_xml = build_radar_metadata_xml(validation["metadata"])
                xsd_path = toolkit.config.get(
                    "ckanext.dataset_transfer.radar.descriptive_xsd_path",
                    str(DEFAULT_RADAR_DATASET_XSD),
                )
                validate_radar_metadata_xml(metadata_xml, xsd_path)
            except Exception as error:
                validation["errors"].append({
                    "field": "metadata",
                    "message": "RADAR descriptive metadata XML is invalid: {}".format(error),
                })
                validation["success"] = False
        return validation

    @classmethod
    def validate(cls, dataset, target, reviewed_metadata=None):
        if target == "radar":
            validation = cls._radar_metadata(dataset, reviewed_metadata)
            return {"valid": validation["success"], "dataset_id": dataset["id"],
                    "target": target, "metadata": validation["metadata"],
                    "errors": validation["errors"], "warnings": validation["warnings"]}
        errors = []
        if not Helper.get_organization_id():
            errors.append({"field": "target_organization", "message": "The LUH destination organization is not configured."})
        return {"valid": not errors, "dataset_id": dataset["id"], "target": target,
                "metadata": {}, "errors": errors, "warnings": []}

    @classmethod
    def publish(cls, dataset, target, reviewed_metadata=None, destination_token=None):
        PublishedDataset.acquire_publish_lock(dataset["id"], target)
        existing = PublishedDataset.get_by_dataset_and_target(dataset["id"], target)
        if existing:
            raise PublishError("already_transferred", "This dataset has already been transferred.",
                               existing_transfer=cls._record(existing))
        incomplete = (PublishedDataset.get_incomplete_radar_transfer(dataset["id"])
                      if target == "radar" else PublishedDataset.get_incomplete_luh_transfer(dataset["id"]))
        if target == "luh" and incomplete:
            raise PublishError("incomplete_transfer", "A destination dataset exists with an incomplete resource transfer; reconcile it before retrying.",
                               existing_transfer=cls._record(incomplete))
        if target == "radar":
            return cls._publish_radar(dataset, reviewed_metadata, incomplete)
        return cls._publish_luh(dataset, destination_token)

    @classmethod
    def _publish_radar(cls, dataset, reviewed_metadata, incomplete):
        validation = cls._radar_metadata(dataset, reviewed_metadata)
        if not validation["success"]:
            raise PublishError("metadata_validation", "RADAR metadata validation failed.",
                               errors=validation["errors"], warnings=validation["warnings"])
        try:
            publisher = RadarPublisher(token_provider=RadarTokenProvider(toolkit.config))
            transfer_state = None
            if incomplete:
                transfer_state = PublishedDataset.decode_incomplete_radar_id(incomplete.published_dataset_id)
                transfer_state["doi"] = incomplete.doi or ""
            result = publisher.publish_dataset(dataset, validation["metadata"], transfer_state=transfer_state)
        except (RadarConfigError, RadarAuthConfigError) as error:
            raise PublishError("configuration", str(error))
        except RadarPublishError as error:
            if error.dataset_id and error.status:
                record = incomplete or PublishedDataset(dataset_id=dataset["id"], publish_time=datetime.utcnow())
                record.doi = error.doi or ""
                record.published_url = publisher.dataset_url(error.dataset_id)
                record.published_dataset_id = PublishedDataset.encode_incomplete_radar_id(error.status, error.dataset_id)
                record.save()
            raise PublishError("destination", str(error), transfer_status=error.status,
                               destination_dataset_id=error.dataset_id, missing_filenames=error.missing)
        record = incomplete or PublishedDataset(dataset_id=dataset["id"], publish_time=datetime.utcnow())
        record.doi = result.get("doi") or ""
        record.published_url = result["published_url"]
        record.published_dataset_id = PublishedDataset.encode_target_id("radar", result["published_dataset_id"])
        record.save()
        result.update({"dataset_id": dataset["id"], "target": "radar", "status": "pending_publication",
                       "destination_dataset_id": result["published_dataset_id"]})
        return result

    @classmethod
    def _publish_luh(cls, dataset, token):
        # Reuse the hardened remote CKAN helpers used by the legacy UI.
        from ckanext.dataset_transfer.controllers.base import BaseController, RemoteAPIError
        if not token or not str(token).strip():
            raise PublishError("credential", "LUH destination authorization is required.")
        organization = Helper.get_organization_id()
        if not organization:
            raise PublishError("configuration", "The LUH destination organization is not configured.")
        headers = {"Authorization": str(token).strip()}
        try:
            org = BaseController._remote_json("get", "organization_show", headers=headers, params={"id": organization})["result"]
            payload = BaseController._prepare_luh_dataset(dataset, org["id"])
            try:
                remote = BaseController._remote_json("get", "package_show", headers=headers, params={"id": payload["name"]})
            except RemoteAPIError as error:
                if error.status != 404:
                    raise
                remote = None
            if remote:
                raise PublishError("destination_conflict", "A destination dataset with this name already exists.")
            created = BaseController._remote_json("post", "package_create", headers=headers, json=payload)["result"]
        except PublishError:
            raise
        except RemoteAPIError as error:
            raise PublishError("destination", str(error), destination_status=error.status)
        url = Helper.get_target_public_url() + "dataset/" + created["name"]
        record = PublishedDataset(dataset_id=dataset["id"], doi=created.get("doi") or "", published_url=url,
            published_dataset_id=PublishedDataset.encode_incomplete_luh_id("resources_pending", created["id"]), publish_time=datetime.utcnow())
        record.save()
        failures = []
        storage = toolkit.config["ckan.storage_path"] + "/resources/"
        for resource in copy.deepcopy(dataset.get("resources", [])):
            try:
                data = resource.copy(); data.pop("datastore_active", None); data["package_id"] = created["id"]
                made = BaseController._remote_json("post", "resource_create", headers=headers, json=data)["result"]
                if resource.get("url_type") == "upload":
                    path = storage + resource["id"][:3] + "/" + resource["id"][3:6] + "/" + resource["id"][6:]
                    with open(path, "rb") as stream:
                        BaseController._remote_json("post", "resource_patch", data={"id": made["id"]}, headers=headers, files={"upload": stream.read()})
            except (RemoteAPIError, IOError, OSError) as error:
                failures.append({"resource_id": resource.get("id"), "message": str(error)})
        if failures:
            record.published_dataset_id = PublishedDataset.encode_incomplete_luh_id("resources_failed", created["id"]); record.save()
            raise PublishError("incomplete_transfer", "The LUH dataset was created but resources failed to transfer.",
                               destination_dataset_id=created["id"], published_url=url, resource_failures=failures)
        record.published_dataset_id = PublishedDataset.encode_target_id("luh", created["id"]); record.save()
        return {"dataset_id": dataset["id"], "target": "luh", "status": "transferred",
                "doi": created.get("doi") or "", "published_url": url,
                "published_dataset_id": created["id"], "destination_dataset_id": created["id"]}

    @classmethod
    def status(cls, dataset_id, target):
        complete = PublishedDataset.get_by_dataset_and_target(dataset_id, target)
        incomplete = (PublishedDataset.get_incomplete_radar_transfer(dataset_id)
                      if target == "radar" else PublishedDataset.get_incomplete_luh_transfer(dataset_id))
        if complete:
            item = cls._record(complete)
            item["status"] = "pending_publication" if target == "radar" else "transferred"
        elif incomplete:
            item = cls._record(incomplete)
        else:
            item = {"status": "not_transferred", "doi": "", "published_url": "", "destination_dataset_id": ""}
        item.update({"dataset_id": dataset_id, "target": target})
        return item

    @staticmethod
    def _record(record):
        radar = PublishedDataset.decode_incomplete_radar_id(record.published_dataset_id)
        luh = PublishedDataset.decode_incomplete_luh_id(record.published_dataset_id)
        target, destination_id = PublishedDataset.decode_target_id(record.published_dataset_id)
        decoded = radar or luh
        return {"status": decoded["status"] if decoded else "transferred", "doi": record.doi or "",
                "published_url": record.published_url or "",
                "destination_dataset_id": decoded["published_dataset_id"] if decoded else destination_id,
                "publish_time": record.publish_time.isoformat() if record.publish_time else None}
