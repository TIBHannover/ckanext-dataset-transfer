# encoding: utf-8

import copy
import json
import logging
import os

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
from ckanext.dataset_transfer.services.radar_metadata_mapping import (
    VOCABULARIES,
    map_ckan_to_radar,
    normalize_reviewed_metadata,
    validate_radar_metadata,
)
from datetime import datetime as _time


log = logging.getLogger(__name__)


class BaseController():

    # base_url = "https://data-neu.uni-hannover.de/api/3/action/"
    # publish_base_url = "https://data-neu.uni-hannover.de/"
    base_url = "https://data.uni-hannover.de/api/3/action/" 
    publish_base_url = "https://data.uni-hannover.de/"

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
        )
        return render_template(
            'publish_page.html',
            pkg=package,
            pkg_dict=package,
            radar_metadata=radar_metadata,
            radar_vocabularies=VOCABULARIES,
            transfer_status=BaseController.get_transfer_status(package["id"]),
        )



   
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
            org_name = Helper.get_organization_id()
            api_token = request.form.get("api_token")
            save_api_token = request.form.get("save_api_token_box")
            terms_of_use_consent = request.form.get("terms_of_usage")
            rights_of_use_consent = request.form.get("rights_of_use")
            use_existing_api_token = request.form.get("token_exist_box")
            dataset = toolkit.get_action('package_show')({}, {'id': package_id})
            log.info(
                "Dataset transfer package loaded package_id=%s target=%s resource_count=%s",
                dataset.get("id"),
                publish_target,
                len(dataset.get("resources") or []),
            )
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
                        publish_target.upper()
                    ),
                    409,
                    existing_transfer=BaseController._transfer_record(
                        existing_transfer, serialize=True
                    ),
                )
            
            if terms_of_use_consent != "true" or rights_of_use_consent != "true":
                log.warning(
                    "Dataset transfer publish rejected package_id=%s reason=missing_consent terms=%s rights=%s",
                    dataset.get("id"),
                    terms_of_use_consent,
                    rights_of_use_consent,
                )
                return BaseController._error_response(
                    "Missing consent",
                    "Terms of usage and rights of use must be accepted.",
                    400
                )

            if publish_target == "radar":
                log.info(
                    "Dataset transfer RADAR publish selected package_id=%s user=%s",
                    dataset.get("id"),
                    getattr(toolkit.g, "user", ""),
                )
                reviewed_metadata = normalize_reviewed_metadata(
                    request.form.get("radar_metadata")
                )
                validation = validate_radar_metadata(reviewed_metadata)
                if not validation["success"]:
                    return BaseController._error_response(
                        "RADAR metadata validation failed",
                        "Please correct the highlighted RADAR metadata fields.",
                        400,
                        errors=validation["errors"],
                        warnings=validation["warnings"],
                    )
                try:
                    radar_result = RadarPublisher().publish_dataset(
                        dataset,
                        validation["metadata"],
                    )
                except RadarConfigError as error:
                    log.exception(
                        "Dataset transfer RADAR configuration failed package_id=%s",
                        dataset.get("id"),
                    )
                    return BaseController._error_response(
                        "RADAR configuration missing", str(error), 400
                    )
                except RadarPublishError as error:
                    log.exception(
                        "Dataset transfer RADAR publish failed package_id=%s",
                        dataset.get("id"),
                    )
                    return BaseController._error_response(
                        "RADAR publish failed", str(error), 502
                    )

                dataset_db_object = PublishedDataset(
                    dataset_id=dataset["id"],
                    doi=radar_result.get("doi") or "",
                    published_url=radar_result["published_url"],
                    published_dataset_id=PublishedDataset.encode_target_id(
                        "radar", radar_result["published_dataset_id"]
                    ),
                    publish_time=_time.now(),
                )
                dataset_db_object.save()
                log.info(
                    "Dataset transfer RADAR publish response package_id=%s radar_dataset_id=%s published_url=%s",
                    dataset.get("id"),
                    radar_result.get("published_dataset_id"),
                    radar_result.get("published_url"),
                )
                return BaseController._json_response(radar_result)

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
                        target_ckan=BaseController.publish_base_url,
                        created_at=_time.now()
                     )
                    api_token_obj.save()

            resources_dir_path = toolkit.config['ckan.storage_path'] + '/resources/'
            headers = {'Authorization' : api_token.strip()}
            params = {'id': org_name}   
            log.info(
                "Dataset transfer LUH organization_show started package_id=%s org=%s",
                package_id,
                org_name
            )
            org_response = requests.get(
                BaseController.base_url + "organization_show",
                headers=headers,
                params=params
            )
            log.info(
                "Dataset transfer LUH organization_show response package_id=%s status=%s body=%s",
                package_id,
                org_response.status_code,
                org_response.text[:1000]
            )
            if org_response.status_code != 200:
                return BaseController._error_response(
                    "Remote organization lookup failed",
                    org_response.text,
                    502
                )
            org_answer = org_response.json()
            if not org_answer.get('success') or not org_answer.get('result'):
                return BaseController._error_response(
                    "Remote organization lookup failed",
                    org_answer.get('error') or "LUH did not return an organization.",
                    502
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
            log.info("Dataset transfer LUH package_create started package_id=%s", package_id)
            dataset_created_answer = requests.post(BaseController.base_url + "package_create", headers=headers, json=dataset_to_publish)
            log.info(
                "Dataset transfer LUH package_create response package_id=%s status=%s body=%s",
                package_id,
                dataset_created_answer.status_code,
                dataset_created_answer.text[:1000]
            )
            dataset_created_json = dataset_created_answer.json()
            if dataset_created_answer.status_code != 200 or "id" not in dataset_created_json.get('result', {}):
                if dataset_created_json.get('error'):
                    error = dataset_created_json['error']
                    return BaseController._error_response(
                        error.get('__type', 'Remote package create failed'),
                        error.get('message') or error,
                        502
                    )
                else:
                    return BaseController._error_response(
                        "Remote package create failed",
                        "LUH did not return a dataset id.",
                        502
                    )
    
            
            just_uploaded_dataset = dataset_created_json['result']
            for res in resources:
                try:
                    headers["Content-Type"] = "application/json"                
                    if res['url_type'] == 'upload':
                        resource_data = copy.deepcopy(res)
                        if resource_data.get('datastore_active'):
                            del resource_data['datastore_active']
                        file_content = {'upload': ''}
                        resource_data['package_id'] = just_uploaded_dataset['id']
                        file_path = resources_dir_path + res['id'][0:3] + '/' + res['id'][3:6] + '/' + res['id'][6:]
                        with open(file_path, 'rb') as file:
                            file_content['upload'] = file.read()
                        
                        log.info(
                            "Dataset transfer LUH resource_create started package_id=%s resource_id=%s",
                            package_id,
                            res.get('id')
                        )
                        created_resource = requests.post(BaseController.base_url + "resource_create", headers=headers, json=resource_data)
                        log.info(
                            "Dataset transfer LUH resource_create response package_id=%s resource_id=%s status=%s body=%s",
                            package_id,
                            res.get('id'),
                            created_resource.status_code,
                            created_resource.text[:1000]
                        )
                        if created_resource.status_code == 200 and 'id' in created_resource.json()['result']:
                            # upload the data file
                            resource_patch_headers = {'Authorization' : api_token.strip()}
                            res_data = {"id": created_resource.json()['result']['id']} 
                            log.info(
                                "Dataset transfer LUH resource_patch upload started package_id=%s resource_id=%s",
                                package_id,
                                res.get('id')
                            )
                            uploaded_file = requests.post(BaseController.base_url + "resource_patch", data=res_data, headers=resource_patch_headers, files=file_content)
                            log.info(
                                "Dataset transfer LUH resource_patch response package_id=%s resource_id=%s status=%s body=%s",
                                package_id,
                                res.get('id'),
                                uploaded_file.status_code,
                                uploaded_file.text[:1000]
                            )
                    
                    else:
                        resource_data = copy.deepcopy(res)
                        if resource_data.get('datastore_active'):
                            del resource_data['datastore_active']                    
                        resource_data['package_id'] = just_uploaded_dataset['id']
                        log.info(
                            "Dataset transfer LUH resource_create started package_id=%s resource_id=%s",
                            package_id,
                            res.get('id')
                        )
                        created_resource = requests.post(BaseController.base_url + "resource_create", headers=headers, json=resource_data)
                        log.info(
                            "Dataset transfer LUH resource_create response package_id=%s resource_id=%s status=%s body=%s",
                            package_id,
                            res.get('id'),
                            created_resource.status_code,
                            created_resource.text[:1000]
                        )
                except Exception:
                    log.exception(
                        "Dataset transfer resource upload failed package_id=%s resource_id=%s",
                        package_id,
                        res.get('id')
                    )
                    continue
                    
            just_uploaded_dataset["published_url"] = BaseController.publish_base_url + "dataset/" + just_uploaded_dataset['name']
            dataset_db_object = PublishedDataset(
                dataset_id=dataset_local_id,
                doi=just_uploaded_dataset.get('doi') or '',
                published_url=just_uploaded_dataset['published_url'],
                published_dataset_id=PublishedDataset.encode_target_id(
                    "luh", just_uploaded_dataset['id']
                ),
                publish_time=_time.now(),
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
        
        except Exception as error:
            log.exception(
                "Dataset transfer publish failed before response package_id=%s",
                request.form.get("package_id")
            )
            return BaseController._error_response("Internal error", str(error), 500)




    def load_publish_form_data():
        try:
            package_id = request.form.get('package_id')
            api_token = request.form.get('api_token')
            use_existing_token = request.form.get('token_exist_box')
            log.info(
                "Dataset transfer organization form request accepted package_id=%s user=%s use_existing_token=%s content_type=%s",
                package_id,
                getattr(toolkit.g, "user", ""),
                use_existing_token,
                request.content_type,
            )
            if not Helper.check_access_edit_package(package_id):
                log.warning(
                    "Dataset transfer organization form rejected package_id=%s reason=not_authorized",
                    package_id,
                )
                return 'Not Authorized'
            
            if use_existing_token == "true":
                # use the user existing api token
                if BaseController.user_has_api_token() == "True":
                    user_id = toolkit.g.userobj.id
                    api_token_obj = PublishApiToken()
                    api_token = api_token_obj.get_by_user(id=user_id).api_token   

            header = {"Authorization" : api_token}
            org_list_url = BaseController.base_url +  "organization_list_for_user"
            response= requests.get(org_list_url, headers=header)
            log.info(
                "Dataset transfer organization list response package_id=%s status=%s body=%s",
                package_id,
                response.status_code,
                response.text[:1000],
            )
            if response.status_code != 200:
                return json.dumps([])
            else:
                data = []
                count = 1
                for org in response.json()["result"]:                    
                    temp = {}
                    temp['id'] = org['name']
                    temp['text'] = org['title']
                    data.append(temp)
                    count += 1
                return json.dumps(data)
        
        except Exception:
            log.exception(
                "Dataset transfer organization form failed package_id=%s",
                request.form.get('package_id'),
            )
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
        target, published_dataset_id = PublishedDataset.decode_target_id(
            record.published_dataset_id
        )
        return {
            "target": target or "legacy",
            "doi": record.doi or "",
            "published_url": record.published_url or "",
            "published_dataset_id": published_dataset_id,
            "publish_time": publish_time,
        }

    @staticmethod
    def get_transfer_status(dataset_id):
        status = {"luh": None, "radar": None, "legacy": []}
        for record in PublishedDataset.get_all_by_dataset(dataset_id):
            item = BaseController._transfer_record(record)
            if item["target"] in ("luh", "radar"):
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
        ckan_root_path = toolkit.config.get('ckan.root_path')
        if  ckan_root_path and 'sfb1368/ckan' in ckan_root_path:
            return "SFB 1368"
        elif ckan_root_path and 'sfb1153/ckan' in ckan_root_path:
            return "SFB 1153"
        else:
            return "SFB 1153"
