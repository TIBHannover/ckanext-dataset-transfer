# encoding: utf-8

import copy
import json
import logging

import requests
from ckanext.dataset_transfer.libs.helper import Helper
from flask import Response, request, render_template
import ckan.plugins.toolkit as toolkit
from ckanext.dataset_transfer.models.published_dataset import PublishedDataset
from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken
from datetime import datetime as _time


log = logging.getLogger(__name__)


class RemoteAPIError(Exception):
    def __init__(self, operation, message, status=None):
        super(RemoteAPIError, self).__init__(message)
        self.operation = operation
        self.status = status


class BaseController():

    remote_timeout = 60

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
            return error.get("message") or error.get("__type") or fallback
        if isinstance(error, str):
            return error
        return fallback

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
                500: "Destination API reported an internal server error.",
            }
            raise RemoteAPIError(
                action,
                status_messages.get(
                    response.status_code,
                    "Destination API returned HTTP {}.".format(response.status_code),
                ),
                response.status_code,
            )
        if payload.get("success") is False:
            raise RemoteAPIError(
                action,
                "Destination API reported a failure.",
                response.status_code,
            )
        return payload

    @staticmethod
    def _remote_failure_response(error, **details):
        message = str(error)
        if error.status:
            message = "{} (HTTP {})".format(message, error.status)
        return BaseController._error_response(
            "Remote {} failed".format(error.operation),
            message,
            502,
            **details
        )


    def publish_page(dataset_name):
        '''
            Render the publish page.
        '''
        package = toolkit.get_action('package_show')({}, {'id': dataset_name})
        if not Helper.check_access_edit_package(package['id']):
                return toolkit.abort(403, "Not Authorized")
        
        if(BaseController.is_dataset_published(package['id'])):
                # dataset is already published
                toolkit.abort(400, "This dataset is already published")

        return render_template('publish_page.html', pkg=package, pkg_dict=package)



   
    def publish():
        '''
            Publish a dataset.
        '''
        
        try:
            log.info("Dataset transfer publish request started")
            package_id = request.form.get("package_id")
            log.info(
                "Dataset transfer publish request accepted package_id=%s user=%s content_type=%s remote_addr=%s form_fields=%s",
                package_id,
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

            PublishedDataset.acquire_publish_lock(dataset["id"], "luh")
            existing_transfer = PublishedDataset.get_by_dataset_and_target(
                dataset["id"], "luh"
            )
            if existing_transfer:
                log.warning(
                    "Dataset transfer rejected package_id=%s reason=already_transferred",
                    dataset["id"],
                )
                return BaseController._error_response(
                    "Already transferred",
                    "This dataset has already been transferred to LUH.",
                    409,
                    existing_transfer=BaseController._transfer_record(
                        existing_transfer, serialize=True
                    ),
                )
            incomplete_luh_transfer = PublishedDataset.get_incomplete_luh_transfer(
                dataset["id"]
            )
            if incomplete_luh_transfer:
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
            dataset_to_publish = copy.deepcopy(dataset)
            dataset_to_publish['resources'] = []
            dataset_to_publish["groups"] = []
            dataset_to_publish["isopen"] = True
            dataset_to_publish["private"] = False
            dataset_to_publish["owner_org"] = org_answer['result']['id']
            dataset_to_publish['id'] = ""
            dataset_to_publish['terms_of_usage'] = "Yes"
            dataset_to_publish['have_copyright'] = "Yes"
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
    


    def is_dataset_published(id):
        '''
            Check if a dataset is already published ot not.
        '''


        db_object = PublishedDataset()
        answer = db_object.get_by_dataset(id=id)
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
            "published_url": record.published_url or "",
            "published_dataset_id": published_dataset_id,
            "publish_time": publish_time,
        }

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
