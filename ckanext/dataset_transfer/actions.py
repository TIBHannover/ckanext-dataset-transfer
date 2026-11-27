import ckan.plugins.toolkit as toolkit

from ckanext.dataset_transfer.libs.helper import Helper
from ckanext.dataset_transfer.services.credentials import CredentialService
from ckanext.dataset_transfer.services.publish import PublishError, PublishService
from ckanext.dataset_transfer.services.radar_metadata_mapping import (
    ALLOWED_FIELDS, FIXED_RESOURCE_TYPE, FIXED_SUBJECT_AREA, VOCABULARIES,
)


def _require_dataset(context, data_dict, permission="package_update"):
    dataset_id = data_dict.get("dataset_id")
    if not dataset_id:
        raise toolkit.ValidationError({"dataset_id": ["Missing value"]})
    dataset = toolkit.get_action("package_show")(context, {"id": dataset_id})
    toolkit.check_access(permission, context, {"id": dataset["id"]})
    return dataset


def _target(data_dict, require_enabled=True):
    target = data_dict.get("target")
    if target not in ("radar", "luh"):
        raise toolkit.ValidationError({"target": ["Must be 'radar' or 'luh'."]})
    if require_enabled and not Helper.target_enabled(target):
        raise toolkit.ValidationError({"target": ["The requested publication target is disabled."]})
    return target


@toolkit.side_effect_free
def dataset_transfer_targets(context, data_dict):
    toolkit.check_access("dataset_transfer_targets", context, data_dict)
    return {"targets": Helper.publication_targets()}


@toolkit.side_effect_free
def dataset_transfer_validate(context, data_dict):
    toolkit.check_access("dataset_transfer_validate", context, data_dict)
    dataset = _require_dataset(context, data_dict)
    target = _target(data_dict)
    return PublishService.validate(dataset, target, data_dict.get("radar_metadata"))


def dataset_transfer_publish(context, data_dict):
    toolkit.check_access("dataset_transfer_publish", context, data_dict)
    dataset = _require_dataset(context, data_dict)
    target = _target(data_dict)
    if data_dict.get("terms_accepted") is not True or data_dict.get("rights_confirmed") is not True:
        raise toolkit.ValidationError({"consent": ["terms_accepted and rights_confirmed must both be JSON true."]})
    destination_token = data_dict.get("luh_api_token")
    if target == "luh" and not destination_token:
        user_obj = CredentialService.user_from_action_context(context)
        record = CredentialService.record_for_user(user_obj)
        destination_token = record.api_token if record else None
    try:
        return PublishService.publish(dataset, target, data_dict.get("radar_metadata"), destination_token)
    except PublishError as error:
        raise toolkit.ValidationError(error.as_dict())


@toolkit.side_effect_free
def dataset_transfer_status(context, data_dict):
    toolkit.check_access("dataset_transfer_status", context, data_dict)
    dataset = _require_dataset(context, data_dict, permission="package_show")
    target = _target(data_dict, require_enabled=False)
    refresh = data_dict.get("refresh", False)
    if not isinstance(refresh, bool):
        raise toolkit.ValidationError({"refresh": ["Must be a JSON boolean."]})
    return PublishService.status(dataset["id"], target, refresh=refresh)


@toolkit.side_effect_free
def dataset_transfer_radar_metadata_schema(context, data_dict):
    toolkit.check_access("dataset_transfer_radar_metadata_schema", context, data_dict)
    return {
        "fields": sorted(ALLOWED_FIELDS),
        "vocabularies": {
            key: [list(item) if isinstance(item, tuple) else item for item in values]
            for key, values in VOCABULARIES.items()
        },
        "fixed": {
            "resource_type": FIXED_RESOURCE_TYPE,
            "required_subject_area": FIXED_SUBJECT_AREA,
            "publication_year": "Assigned by RADAR4Ing",
            "funding_references": "Entries marked fixed are controlled by CKAN policy.",
        },
    }


def _credential_user(context):
    user = CredentialService.user_from_action_context(context)
    if not user:
        raise toolkit.NotAuthorized("Authentication required")
    return user


@toolkit.side_effect_free
def dataset_transfer_credential_status(context, data_dict):
    toolkit.check_access("dataset_transfer_credential_status", context, data_dict)
    return CredentialService.presentation_for_user(_credential_user(context))


def dataset_transfer_credential_save(context, data_dict):
    toolkit.check_access("dataset_transfer_credential_save", context, data_dict)
    user = _credential_user(context)
    if data_dict.get("confirm_save") is not True:
        raise toolkit.ValidationError({"confirm_save": ["Explicit confirmation is required."]})
    existing = CredentialService.record_for_user(user)
    if existing and data_dict.get("replace_existing") is not True:
        raise toolkit.ValidationError({"replace_existing": ["Explicit replacement confirmation is required."]})
    try:
        CredentialService.save_for_user(user, data_dict.get("luh_api_token"))
    except ValueError as error:
        raise toolkit.ValidationError({"luh_api_token": [str(error)]})
    return CredentialService.presentation_for_user(user)


def dataset_transfer_credential_delete(context, data_dict):
    toolkit.check_access("dataset_transfer_credential_delete", context, data_dict)
    if data_dict.get("confirm_delete") is not True:
        raise toolkit.ValidationError({"confirm_delete": ["Explicit confirmation is required."]})
    user = _credential_user(context)
    CredentialService.remove_for_user(user)
    return CredentialService.presentation_for_user(user)


@toolkit.side_effect_free
def dataset_transfer_credential_test(context, data_dict):
    toolkit.check_access("dataset_transfer_credential_test", context, data_dict)
    return CredentialService.test_for_user(
        _credential_user(context), data_dict.get("luh_api_token")
    )


def get_actions():
    return {
        "dataset_transfer_targets": dataset_transfer_targets,
        "dataset_transfer_validate": dataset_transfer_validate,
        "dataset_transfer_publish": dataset_transfer_publish,
        "dataset_transfer_status": dataset_transfer_status,
        "dataset_transfer_radar_metadata_schema": dataset_transfer_radar_metadata_schema,
        "dataset_transfer_credential_status": dataset_transfer_credential_status,
        "dataset_transfer_credential_save": dataset_transfer_credential_save,
        "dataset_transfer_credential_delete": dataset_transfer_credential_delete,
        "dataset_transfer_credential_test": dataset_transfer_credential_test,
    }
