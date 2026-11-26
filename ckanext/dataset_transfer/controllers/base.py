# encoding: utf-8

import copy
import json
import logging
import os
import re
from urllib.parse import urlparse

import requests
from ckanext.dataset_transfer.libs.helper import Helper
from flask import Response, request, render_template
import ckan.plugins.toolkit as toolkit
from ckanext.dataset_transfer.models.published_dataset import PublishedDataset
from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken
from ckanext.dataset_transfer.services.radar import (
    RadarConfigError,
    RadarPublishError,
    RadarPublisher,
)
from ckanext.dataset_transfer.services.radar_auth import (
    RadarAuthConfigError,
    RadarTokenProvider,
)
from ckanext.dataset_transfer.services.radar_metadata_mapping import (
    VOCABULARIES,
    apply_fixed_radar_metadata,
    fixed_radar_metadata_errors,
    map_ckan_to_radar,
    normalize_reviewed_metadata,
    validate_radar_metadata,
)
from ckanext.dataset_transfer.services.radar_reference_mapping import (
    get_ckan_reference_descriptions,
)
from datetime import datetime as _time


log = logging.getLogger(__name__)


class RemoteAPIError(Exception):
    def __init__(self, operation, message, status=None, validation_errors=None):
        super(RemoteAPIError, self).__init__(message)
        self.operation = operation
        self.status = status
        self.validation_errors = validation_errors or {}


class BaseController():

    remote_timeout = 60
    destination_managed_package_fields = (
        "creator_user_id",
        "display_name",
        "metadata_created",
        "metadata_modified",
        "num_resources",
        "num_tags",
        "organization",
        "relationships_as_object",
        "relationships_as_subject",
        "revision_id",
        "state",
        "tracking_summary",
    )
    sensitive_error_key = re.compile(
        r"authorization|cookie|credential|csrf|password|secret|token|api.?key",
        re.IGNORECASE,
    )
    sensitive_error_text = re.compile(
        r"authorization|cookie|credential|csrf|password|secret|api.?token|"
        r"api.?key|bearer\s+\S+",
        re.IGNORECASE,
    )

    @staticmethod
    def _json_response(data, status=200):
        return Response(
            json.dumps(data),
            status=status,
            content_type='application/json; charset=utf-8'
        )

    @staticmethod
    def _error_response(error, message, status=500, **details):
        payload = {
            "success": False,
            "error": error,
            "message": message
        }
        payload.update(details)
        return BaseController._json_response(payload, status=status)

    @staticmethod
    def _remote_error_message(payload, fallback):
        if not isinstance(payload, dict):
            return fallback
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("__type")
            return BaseController._safe_error_text(message) or fallback
        if isinstance(error, str):
            return BaseController._safe_error_text(error) or fallback
        return fallback

    @staticmethod
    def _safe_error_text(value):
        if not isinstance(value, str):
            return ""
        value = " ".join(value.split())
        if not value or BaseController.sensitive_error_text.search(value):
            return ""
        return value[:500]

    @staticmethod
    def _safe_validation_errors(payload):
        """Extract CKAN validation messages without reflecting credentials."""
        if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
            return {}
        safe_errors = {}
        for field, value in payload["error"].items():
            if (
                not isinstance(field, str)
                or field.startswith("__")
                or field == "message"
                or BaseController.sensitive_error_key.search(field)
            ):
                continue
            safe_field = re.sub(r"[^A-Za-z0-9_. -]", "", field)[:80]
            if not safe_field:
                continue
            values = value if isinstance(value, (list, tuple)) else [value]
            messages = []
            for item in values[:5]:
                message = BaseController._safe_error_text(item)
                if message:
                    messages.append(message)
            if messages:
                safe_errors[safe_field] = messages
        return safe_errors

    @staticmethod
    def _validation_error_summary(validation_errors):
        details = []
        for field, messages in list(validation_errors.items())[:5]:
            details.append("{}: {}".format(field, "; ".join(messages)))
        return " ".join(details)

    @staticmethod
    def _remote_json(method, action, **kwargs):
        url = Helper.get_target_api_url() + action
        kwargs.setdefault("timeout", BaseController.remote_timeout)
        try:
            request_method = getattr(requests, method)
            response = request_method(url, **kwargs)
        except requests.Timeout:
            raise RemoteAPIError(action, "Destination API request timed out.")
        except requests.ConnectionError:
            raise RemoteAPIError(action, "Destination API connection failed.")
        except requests.RequestException:
            raise RemoteAPIError(action, "Destination API request failed.")

        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise RemoteAPIError(
                action,
                "Destination API returned an invalid JSON response.",
                response.status_code,
            )
        if not isinstance(payload, dict):
            raise RemoteAPIError(
                action,
                "Destination API returned an unexpected response structure.",
                response.status_code,
            )
        if response.status_code != 200:
            status_messages = {
                401: "Destination API authentication failed.",
                403: "Destination API authorization failed.",
                404: "Destination API endpoint or object was not found.",
                409: (
                    "Destination CKAN rejected the request because of a conflict. "
                    "The dataset name may already exist or a field may be invalid."
                ),
                500: "Destination API reported an internal server error.",
            }
            validation_errors = BaseController._safe_validation_errors(payload)
            message = status_messages.get(
                response.status_code,
                "Destination API returned HTTP {}.".format(response.status_code),
            )
            if response.status_code in (400, 409, 422):
                summary = BaseController._validation_error_summary(validation_errors)
                if summary:
                    message = "{} {}".format(message, summary)
            raise RemoteAPIError(
                action,
                message,
                response.status_code,
                validation_errors,
            )
        if payload.get("success") is False:
            validation_errors = BaseController._safe_validation_errors(payload)
            message = BaseController._remote_error_message(
                payload, "Destination API reported a failure."
            )
            summary = BaseController._validation_error_summary(validation_errors)
            if summary:
                message = "{} {}".format(message, summary)
            raise RemoteAPIError(
                action,
                message,
                response.status_code,
                validation_errors,
            )
        return payload

    @staticmethod
    def _remote_failure_response(error, **details):
        message = str(error)
        if error.status:
            message = "{} (HTTP {})".format(message, error.status)
            details["destination_status"] = error.status
        if error.validation_errors:
            details["validation_errors"] = error.validation_errors
        return BaseController._error_response(
            "Remote {} failed".format(error.operation),
            message,
            409 if error.status == 409 else 502,
            **details
        )

    @staticmethod
    def _prepare_luh_dataset(dataset, destination_organization_id):
        """Copy source metadata while dropping source-CKAN managed fields."""
        dataset_to_publish = copy.deepcopy(dataset)
        dataset_to_publish.pop("id", None)
        for field in BaseController.destination_managed_package_fields:
            dataset_to_publish.pop(field, None)
        dataset_to_publish["resources"] = []
        dataset_to_publish["groups"] = []
        dataset_to_publish["isopen"] = True
        dataset_to_publish["private"] = False
        dataset_to_publish["owner_org"] = destination_organization_id
        dataset_to_publish["terms_of_usage"] = "Yes"
        dataset_to_publish["have_copyright"] = "Yes"
        return dataset_to_publish


    def publish_page(dataset_name):
        '''
            Render the publish page.
        '''
        package = toolkit.get_action('package_show')({}, {'id': dataset_name})
        if not Helper.check_access_edit_package(package['id']):
                return toolkit.abort(403, "Not Authorized")
        
        configured_publisher = toolkit.config.get(
            "ckanext.dataset_transfer.radar.publisher"
        ) or os.environ.get("CKANEXT_DATASET_TRANSFER_RADAR_PUBLISHER")
        project_id = toolkit.config.get("ckanext.crc.project.id") or os.environ.get(
            "CKANEXT__CRC__PROJECT__ID"
        )
        award_number = toolkit.config.get(
            "ckanext.dataset_transfer.radar.dfg_award_number"
        ) or os.environ.get("CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER")
        radar_metadata = map_ckan_to_radar(
            package,
            configured_publisher,
            project_id=project_id,
            dfg_award_number=award_number,
            reference_descriptions=get_ckan_reference_descriptions(package),
        )
        return render_template(
            'publish_page.html',
            pkg=package,
            pkg_dict=package,
            stored_api_token=BaseController.stored_api_token_info(),
            transfer_status=BaseController.get_transfer_status(package["id"]),
            radar_metadata=radar_metadata,
            radar_vocabularies=VOCABULARIES,
            radar_policy_errors=fixed_radar_metadata_errors(
                package, project_id, award_number
            ),
        )

    @staticmethod
    def stored_api_token_info():
        """Return only presentation-safe metadata for the current user's token."""
        if not getattr(toolkit.g, "user", None):
            return {"available": False, "suffix": ""}
        record = PublishApiToken.get_by_user(toolkit.g.userobj.id)
        if not record:
            return {"available": False, "suffix": ""}
        token = record.api_token or ""
        return {"available": True, "suffix": token[-4:] if token else ""}



   
    def publish():
        '''
            Publish a dataset.
        '''
        
        try:
            package_id = request.form.get("package_id")
            publish_target = request.form.get("publish_target") or "luh"
            log.info(
                "Dataset transfer publish request accepted package_id=%s target=%s user=%s content_type=%s remote_addr=%s form_fields=%s",
                package_id,
                publish_target,
                getattr(toolkit.g, "user", ""),
                request.content_type,
                request.remote_addr,
                sorted(key for key in request.form.keys() if key != "api_token"),
            )
            api_token = request.form.get("api_token")
            save_api_token = request.form.get("save_api_token_box")
            terms_of_use_consent = request.form.get("terms_of_usage")
            rights_of_use_consent = request.form.get("rights_of_use")
            use_existing_api_token = request.form.get("token_exist_box")
            dataset = toolkit.get_action('package_show')({}, {'id': package_id})
            if not Helper.check_access_edit_package(dataset['id']):
                log.warning(
                    "Dataset transfer publish rejected package_id=%s reason=not_authorized user=%s",
                    dataset.get("id"),
                    getattr(toolkit.g, "user", ""),
                )
                return BaseController._error_response(
                    "Not Authorized", "Not Authorized", 403
                )

            if publish_target not in ("luh", "radar"):
                return BaseController._error_response(
                    "Invalid publish target",
                    "Unknown publish target: {}".format(publish_target),
                    400,
                )

            if not Helper.target_enabled(publish_target):
                return BaseController._error_response(
                    "Destination disabled",
                    "The requested publication target is disabled.",
                    400,
                )

            PublishedDataset.acquire_publish_lock(dataset["id"], publish_target)
            existing_transfer = PublishedDataset.get_by_dataset_and_target(
                dataset["id"], publish_target
            )
            if existing_transfer:
                log.warning(
                    "Dataset transfer rejected package_id=%s target=%s reason=already_transferred",
                    dataset["id"],
                    publish_target,
                )
                return BaseController._error_response(
                    "Already transferred",
                    "This dataset has already been transferred to {}.".format(
                        "RADAR4Ing" if publish_target == "radar" else "LUH"
                    ),
                    409,
                    existing_transfer=BaseController._transfer_record(
                        existing_transfer, serialize=True
                    ),
                )
            incomplete_radar_transfer = None
            if publish_target == "radar":
                incomplete_radar_transfer = (
                    PublishedDataset.get_incomplete_radar_transfer(dataset["id"])
                )
            else:
                incomplete_luh_transfer = PublishedDataset.get_incomplete_luh_transfer(
                    dataset["id"]
                )
            if publish_target == "luh" and incomplete_luh_transfer:
                return BaseController._error_response(
                    "Incomplete transfer requires reconciliation",
                    "A destination dataset was already created, but its "
                    "resource transfer did not complete. Reconcile that "
                    "dataset before retrying publication.",
                    409,
                    existing_transfer=BaseController._transfer_record(
                        incomplete_luh_transfer, serialize=True
                    ),
                )
            legacy_transfer = PublishedDataset.get_by_dataset(dataset["id"])
            if legacy_transfer:
                target, _ = PublishedDataset.decode_target_id(
                    legacy_transfer.published_dataset_id
                )
                if not target:
                    return BaseController._error_response(
                        "Already published",
                        "A legacy publication record already exists for this dataset.",
                        409,
                    )
            
            if terms_of_use_consent != "true" or rights_of_use_consent != "true":
                return BaseController._error_response(
                    "Missing consent",
                    "Terms of usage and rights of use must be accepted.",
                    400
                )

            if publish_target == "radar":
                return BaseController._publish_to_radar(
                    dataset, incomplete_radar_transfer
                )

            org_name = Helper.get_organization_id()
            if not org_name:
                return BaseController._error_response(
                    "Missing configuration",
                    "ckanext.dataset_transfer.target_organization must be "
                    "configured with a verified destination organization.",
                    500,
                )
            if use_existing_api_token == "true":
                # use the user existing api token
                if BaseController.user_has_api_token() == "True":
                    user_id = toolkit.g.userobj.id
                    api_token_obj = PublishApiToken()
                    api_token = api_token_obj.get_by_user(id=user_id).api_token                   
                   
                else:
                    return BaseController._error_response(
                        "Invalid request", "No saved API token found.", 403
                    )
            
            else:
                # get the api token from user
                if not api_token or not api_token.strip():
                    return BaseController._error_response(
                        "Invalid request", "A destination API token is required.", 400
                    )
                if save_api_token == "true":
                    # delete the old one if exist
                    if BaseController.user_has_api_token() == "True":
                        user_id = toolkit.g.userobj.id
                        api_token_obj = PublishApiToken()
                        api_token_record = api_token_obj.get_by_user(id=user_id)
                        api_token_record.delete()
                        api_token_record.commit()

                    # save the api token
                    api_token_obj = PublishApiToken(
                        api_token=api_token,
                        user_id=toolkit.g.userobj.id,
                        target_ckan=Helper.get_target_public_url(),
                        created_at=_time.now()
                     )
                    api_token_obj.save()

            if not api_token or not api_token.strip():
                return BaseController._error_response(
                    "Invalid request", "A destination API token is required.", 400
                )

            resources_dir_path = toolkit.config['ckan.storage_path'] + '/resources/'
            headers = {'Authorization': api_token.strip()}
            try:
                org_answer = BaseController._remote_json(
                    "get",
                    "organization_show",
                    headers=headers,
                    params={'id': org_name},
                )
            except RemoteAPIError as error:
                return BaseController._remote_failure_response(error)
            if not org_answer.get('success') or not isinstance(
                org_answer.get('result'), dict
            ) or not org_answer['result'].get('id'):
                return BaseController._error_response(
                    "Remote organization_show failed",
                    "Destination CKAN did not return a valid organization.",
                    502,
                )
            resources = copy.deepcopy(dataset.get('resources', []))
            dataset_local_id = dataset['id']
            dataset_to_publish = BaseController._prepare_luh_dataset(
                dataset, org_answer['result']['id']
            )
            headers["Content-Type"] = "application/json"
            try:
                existing_remote = BaseController._remote_json(
                    "get",
                    "package_show",
                    headers=headers,
                    params={"id": dataset_to_publish.get("name")},
                )
            except RemoteAPIError as error:
                if error.status == 404:
                    existing_remote = None
                else:
                    return BaseController._remote_failure_response(error)
            if existing_remote and isinstance(existing_remote.get("result"), dict):
                remote_dataset = existing_remote["result"]
                return BaseController._error_response(
                    "Destination dataset requires reconciliation",
                    "A destination dataset with this name already exists. "
                    "Verify it before retrying publication.",
                    409,
                    published_dataset_id=remote_dataset.get("id") or "",
                    published_url=(
                        Helper.get_target_public_url()
                        + "dataset/"
                        + (remote_dataset.get("name") or dataset_to_publish["name"])
                    ),
                )
            try:
                dataset_created_json = BaseController._remote_json(
                    "post",
                    "package_create",
                    headers=headers,
                    json=dataset_to_publish,
                )
            except RemoteAPIError as error:
                return BaseController._remote_failure_response(error)
            just_uploaded_dataset = dataset_created_json.get('result')
            if not isinstance(just_uploaded_dataset, dict) or not (
                just_uploaded_dataset.get('id')
                and just_uploaded_dataset.get('name')
            ):
                return BaseController._error_response(
                    "Remote package_create failed",
                    "Destination CKAN did not return a valid dataset.",
                    502,
                )

            just_uploaded_dataset["published_url"] = (
                Helper.get_target_public_url()
                + "dataset/"
                + just_uploaded_dataset['name']
            )
            dataset_db_object = PublishedDataset(
                dataset_id=dataset_local_id,
                doi=just_uploaded_dataset.get('doi') or '',
                published_url=just_uploaded_dataset['published_url'],
                published_dataset_id=PublishedDataset.encode_incomplete_luh_id(
                    "resources_pending", just_uploaded_dataset['id']
                ),
                publish_time=_time.now(),
            )
            dataset_db_object.save()

            resource_failures = []
            for res in resources:
                try:
                    headers["Content-Type"] = "application/json"
                    resource_data = copy.deepcopy(res)
                    resource_data.pop('datastore_active', None)
                    resource_data['package_id'] = just_uploaded_dataset['id']
                    if res.get('url_type') == 'upload':
                        file_path = resources_dir_path + res['id'][0:3] + '/' + res['id'][3:6] + '/' + res['id'][6:]
                        with open(file_path, 'rb') as file:
                            file_content = {'upload': file.read()}

                        created_resource_json = BaseController._remote_json(
                            "post",
                            "resource_create",
                            headers=headers,
                            json=resource_data,
                        )
                        created_result = created_resource_json.get('result')
                        if not isinstance(created_result, dict) or not created_result.get('id'):
                            raise RemoteAPIError(
                                "resource_create",
                                "Destination CKAN did not return a resource id.",
                            )
                        BaseController._remote_json(
                            "post",
                            "resource_patch",
                            data={"id": created_result['id']},
                            headers={'Authorization': api_token.strip()},
                            files=file_content,
                        )
                    else:
                        created_resource_json = BaseController._remote_json(
                            "post",
                            "resource_create",
                            headers=headers,
                            json=resource_data,
                        )
                        created_result = created_resource_json.get('result')
                        if not isinstance(created_result, dict) or not created_result.get('id'):
                            raise RemoteAPIError(
                                "resource_create",
                                "Destination CKAN did not return a resource id.",
                            )
                except (IOError, OSError) as error:
                    log.exception(
                        "Dataset transfer local resource read failed package_id=%s resource_id=%s",
                        package_id,
                        res.get('id')
                    )
                    resource_failures.append({
                        "resource_id": res.get('id'),
                        "operation": "local_file_read",
                        "message": "The local uploaded file could not be read.",
                    })
                except RemoteAPIError as error:
                    log.warning(
                        "Dataset transfer resource failed package_id=%s resource_id=%s operation=%s status=%s",
                        package_id,
                        res.get('id'),
                        error.operation,
                        error.status,
                    )
                    failure = {
                        "resource_id": res.get('id'),
                        "operation": error.operation,
                        "message": str(error),
                    }
                    if error.status:
                        failure["status"] = error.status
                    resource_failures.append(failure)

            if resource_failures:
                dataset_db_object.published_dataset_id = (
                    PublishedDataset.encode_incomplete_luh_id(
                        "resources_failed", just_uploaded_dataset['id']
                    )
                )
                dataset_db_object.save()
                return BaseController._error_response(
                    "Resource transfer incomplete",
                    "The destination dataset was created, but one or more "
                    "resources failed to transfer. Manual reconciliation is required.",
                    502,
                    published_dataset_id=just_uploaded_dataset['id'],
                    published_url=just_uploaded_dataset['published_url'],
                    resource_failures=resource_failures,
                )

            dataset_db_object.published_dataset_id = PublishedDataset.encode_target_id(
                "luh", just_uploaded_dataset['id']
            )
            dataset_db_object.save()
            log.info(
                "Dataset transfer upload completed package_id=%s published_dataset_id=%s published_url=%s",
                package_id,
                just_uploaded_dataset['id'],
                just_uploaded_dataset['published_url']
            )
            response_data = {
                "success": True,
                "doi": just_uploaded_dataset.get('doi') or '',
                "published_url": just_uploaded_dataset['published_url'],
                "published_dataset_id": just_uploaded_dataset['id']
            }
            log.info(
                "Dataset transfer backend response returned to browser package_id=%s success=True",
                package_id
            )
            return BaseController._json_response(response_data)
        
        except Exception:
            log.exception(
                "Dataset transfer publish failed before response package_id=%s",
                request.form.get("package_id")
            )
            return BaseController._error_response(
                "Internal error",
                "Dataset publication failed unexpectedly. Check the CKAN logs.",
                500,
            )

    @staticmethod
    def _publish_to_radar(dataset, incomplete_radar_transfer=None):
        """Validate reviewed metadata and continue through the RADAR publisher."""
        reviewed_metadata = normalize_reviewed_metadata(
            request.form.get("radar_metadata")
        )
        project_id = toolkit.config.get(
            "ckanext.crc.project.id"
        ) or os.environ.get("CKANEXT__CRC__PROJECT__ID")
        award_number = toolkit.config.get(
            "ckanext.dataset_transfer.radar.dfg_award_number"
        ) or os.environ.get(
            "CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER"
        )
        reviewed_metadata = apply_fixed_radar_metadata(
            reviewed_metadata,
            dataset,
            project_id=project_id,
            dfg_award_number=award_number,
            reference_descriptions=get_ckan_reference_descriptions(dataset),
        )
        validation = validate_radar_metadata(reviewed_metadata)
        policy_errors = fixed_radar_metadata_errors(
            dataset, project_id, award_number
        )
        if policy_errors:
            validation["errors"].extend(policy_errors)
            validation["success"] = False
        if not validation["success"]:
            return BaseController._error_response(
                "RADAR metadata validation failed",
                "Please correct the highlighted RADAR metadata fields.",
                400,
                errors=validation["errors"],
                warnings=validation["warnings"],
            )

        try:
            token_provider = RadarTokenProvider(toolkit.config)
            radar_publisher = RadarPublisher(token_provider=token_provider)
            transfer_state = None
            if incomplete_radar_transfer:
                transfer_state = PublishedDataset.decode_incomplete_radar_id(
                    incomplete_radar_transfer.published_dataset_id
                )
                transfer_state["doi"] = incomplete_radar_transfer.doi or ""
            radar_result = radar_publisher.publish_dataset(
                dataset,
                validation["metadata"],
                transfer_state=transfer_state,
            )
        except (RadarConfigError, RadarAuthConfigError) as error:
            log.exception(
                "Dataset transfer RADAR configuration failed package_id=%s",
                dataset.get("id"),
            )
            return BaseController._error_response(
                "RADAR authentication not configured", str(error), 503
            )
        except RadarPublishError as error:
            log.exception(
                "Dataset transfer RADAR publish failed package_id=%s "
                "dataset_id=%s status=%s missing=%s",
                dataset.get("id"),
                error.dataset_id,
                error.status,
                error.missing,
            )
            if error.dataset_id and error.status:
                published_url = radar_publisher.dataset_url(error.dataset_id)
                if incomplete_radar_transfer:
                    incomplete_radar_transfer.doi = error.doi or ""
                    incomplete_radar_transfer.published_url = published_url
                    incomplete_radar_transfer.published_dataset_id = (
                        PublishedDataset.encode_incomplete_radar_id(
                            error.status, error.dataset_id
                        )
                    )
                    incomplete_radar_transfer.save()
                else:
                    incomplete_radar_transfer = PublishedDataset(
                        dataset_id=dataset["id"],
                        doi=error.doi or "",
                        published_url=published_url,
                        published_dataset_id=(
                            PublishedDataset.encode_incomplete_radar_id(
                                error.status, error.dataset_id
                            )
                        ),
                        publish_time=_time.now(),
                    )
                    incomplete_radar_transfer.save()
            return BaseController._error_response(
                "RADAR publish failed",
                str(error),
                502,
                transfer_status=error.status,
                radar_dataset_id=error.dataset_id,
                missing_filenames=error.missing,
            )

        publication = incomplete_radar_transfer or PublishedDataset(
            dataset_id=dataset["id"], publish_time=_time.now()
        )
        publication.doi = radar_result.get("doi") or ""
        publication.published_url = radar_result["published_url"]
        publication.published_dataset_id = PublishedDataset.encode_target_id(
            "radar", radar_result["published_dataset_id"]
        )
        publication.save()
        log.info(
            "Dataset transfer RADAR publish completed package_id=%s "
            "radar_dataset_id=%s published_url=%s",
            dataset.get("id"),
            radar_result.get("published_dataset_id"),
            radar_result.get("published_url"),
        )
        return BaseController._json_response(radar_result)




    def load_publish_form_data():
        try:
            package_id = request.form.get('package_id')
            api_token = request.form.get('api_token')
            use_existing_token = request.form.get('token_exist_box')
            if not Helper.check_access_edit_package(package_id):
                return 'Not Authorized'
            
            if use_existing_token == "true":
                # use the user existing api token
                if BaseController.user_has_api_token() == "True":
                    user_id = toolkit.g.userobj.id
                    api_token_obj = PublishApiToken()
                    api_token = api_token_obj.get_by_user(id=user_id).api_token   

            header = {"Authorization": api_token}
            try:
                answer = BaseController._remote_json(
                    "get", "organization_list_for_user", headers=header
                )
            except RemoteAPIError as error:
                log.warning(
                    "Dataset transfer organization list failed package_id=%s operation=%s status=%s",
                    package_id,
                    error.operation,
                    error.status,
                )
                return json.dumps([])
            result = answer.get("result")
            if not isinstance(result, list):
                return json.dumps([])
            return json.dumps([
                {'id': org['name'], 'text': org['title']}
                for org in result
                if isinstance(org, dict) and org.get('name') and org.get('title')
            ])
        
        except:
            return json.dumps([])
    


    def is_dataset_published(id, target=None):
        '''
            Check if a dataset is already published ot not.
        '''


        if target:
            answer = PublishedDataset.get_by_dataset_and_target(id, target)
        else:
            answer = PublishedDataset.get_by_dataset(id=id)
        if not answer:
            return False
        return True
    

    @staticmethod
    def _transfer_record(record, serialize=False):
        publish_time = record.publish_time
        if serialize and publish_time:
            publish_time = publish_time.isoformat()
        incomplete = PublishedDataset.decode_incomplete_radar_id(
            record.published_dataset_id
        )
        if incomplete:
            target = "radar_incomplete"
            published_dataset_id = incomplete["published_dataset_id"]
            transfer_status = incomplete["status"]
        else:
            incomplete = PublishedDataset.decode_incomplete_luh_id(
                record.published_dataset_id
            )
            if incomplete:
                target = "luh_incomplete"
                published_dataset_id = incomplete["published_dataset_id"]
                transfer_status = incomplete["status"]
            else:
                target, published_dataset_id = PublishedDataset.decode_target_id(
                    record.published_dataset_id
                )
                transfer_status = "successful_transfer" if target else None
        return {
            "target": target or "legacy",
            "status": transfer_status,
            "doi": record.doi or "",
            "published_url": BaseController._safe_published_url(record.published_url),
            "published_dataset_id": published_dataset_id,
            "publish_time": publish_time,
        }

    @staticmethod
    def _safe_published_url(value):
        value = value or ""
        parsed = urlparse(value)
        return value if parsed.scheme in ("http", "https") and parsed.netloc else ""

    @staticmethod
    def get_transfer_status(dataset_id):
        status = {
            "luh": None,
            "radar": None,
            "luh_incomplete": None,
            "radar_incomplete": None,
            "legacy": [],
        }
        for record in PublishedDataset.get_all_by_dataset(dataset_id):
            item = BaseController._transfer_record(record)
            if item["target"] in (
                "luh", "luh_incomplete", "radar", "radar_incomplete"
            ):
                status[item["target"]] = item
            else:
                status["legacy"].append(item)
        return status

    def user_has_api_token():
        '''
            Check a user has api token in database or not.
        '''

        if hasattr(toolkit.g, 'user'):
            if toolkit.g.user:
                user_id = toolkit.g.userobj.id
                api_token_obj = PublishApiToken()
                if not api_token_obj.get_by_user(user_id):
                    return str(False)
                return str(True)
        
        return toolkit.abort(404, "")
    



    def get_published_doi_and_url(dataset_id):
        '''
            Get the doi and url for a published dataset.
        '''

        db_rec = PublishedDataset()
        result = db_rec.get_by_dataset(id=dataset_id)
        return [result.doi, result.published_url]


    def which_sfb():
        return Helper.get_organization_id()
