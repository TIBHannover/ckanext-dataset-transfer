import ckan.plugins.toolkit as toolkit

from ckanext.dataset_transfer.libs.helper import Helper
from ckanext.dataset_transfer.services.credentials import CredentialService
from ckanext.dataset_transfer.services.publish import PublishError, PublishService


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
    return PublishService.status(dataset["id"], target)


def get_actions():
    return {
        "dataset_transfer_targets": dataset_transfer_targets,
        "dataset_transfer_validate": dataset_transfer_validate,
        "dataset_transfer_publish": dataset_transfer_publish,
        "dataset_transfer_status": dataset_transfer_status,
    }
