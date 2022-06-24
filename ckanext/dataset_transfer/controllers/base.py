# encoding: utf-8

import json
from os import abort
import requests
from ckanext.dataset_transfer.libs.helper import Helper
from flask import request, render_template
import ckan.plugins.toolkit as toolkit
import requests, json


class BaseController():

    base_url = "https://data-neu.uni-hannover.de/api/3/action/"


    def publish_page(dataset_name):
        '''
            Render the publish page.
        '''
        package = toolkit.get_action('package_show')({}, {'name_or_id': dataset_name})
        if not Helper.check_access_edit_package(package['id']):
                return toolkit.abort(403, "Not Authorized")

        return render_template('publish_page.html', pkg_dict=package)



   
    def publish():
        '''
            Publish a dataset.
        '''

        package_id = request.form.get("package_id")
        org_name = request.form.get("org")
        api_token = request.form.get("api_token")
        api_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJhUkZXRkZkUEtEYkVtUHREY2FYdDFpeWh2QzIyOVo3ZU0wRzZ2T0Z5dDB3IiwiaWF0IjoxNjU0ODY1NjAxfQ.JslZDQ7NrdLjhoj7EvQNGfMWh953yk-k7Snz78VwRpk"
        dataset = toolkit.get_action('package_show')({}, {'name_or_id': package_id})
        if not Helper.check_access_edit_package(dataset['id']):
                return toolkit.abort(403, "Not Authorized")

        resources_dir_path = toolkit.config['ckan.storage_path'] + '/resources/'
        headers = {'Authorization' : api_token.strip()}
        params = {'id': org_name}
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")
        # print("()(9999999999999999999999999999999999999999999999999999999999999999999999999999999)")       
        org_answer = requests.get(BaseController.base_url + "organization_show", headers=headers, params=params).json()
        
        resources = dataset['resources']
        dataset['resources'] = []
        dataset["groups"] = []
        dataset["isopen"] = True
        dataset["private"] = False
        dataset["owner_org"] = org_answer['result']['id']
        dataset['id'] = ""
        dataset['terms_of_usage'] = "Yes"
        dataset['have_copyright'] = "Yes"
        headers["Content-Type"] = "application/json"
        dataset_created_answer = requests.post(BaseController.base_url + "package_create", headers=headers, json=dataset)        
        if dataset_created_answer.status_code != 200 or "id" not in dataset_created_answer.json()['result'].keys():
            return '500'
        
        just_uploaded_dataset = dataset_created_answer.json()['result']
        for res in resources:
            headers["Content-Type"] = "application/json"
            if res['url_type'] == 'upload':
                resource_data = res
                file_content = {'upload': ''}
                resource_data['package_id'] = just_uploaded_dataset['id']
                file_path = resources_dir_path + res['id'][0:3] + '/' + res['id'][3:6] + '/' + res['id'][6:]
                with open(file_path, 'rb') as file:
                    file_content['upload'] = file.read()

                created_resource = requests.post(BaseController.base_url + "resource_create", headers=headers, json=resource_data)
                if created_resource.status_code == 200 and 'id' in created_resource.json()['result']:
                    resource_patch_headers = {'Authorization' : api_token.strip()}
                    res_data = {"id": created_resource.json()['result']['id']} 
                    uploaded_file = requests.post(BaseController.base_url + "resource_patch", data=res_data, headers=resource_patch_headers, files=file_content)
                    print(uploaded_file.json())
                    
            
            else:
                resource_data = res
                resource_data['package_id'] = just_uploaded_dataset['id']
                created_resource = requests.post(BaseController.base_url + "resource_create", headers=headers, json=resource_data)
                
            
        return just_uploaded_dataset




    def load_publish_form_data():
        try:
            package_id = request.form.get('package_id')
            api_token = request.form.get('api_token')
            if not Helper.check_access_edit_package(package_id):
                return 'Not Authorized'
            
            # api_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJhUkZXRkZkUEtEYkVtUHREY2FYdDFpeWh2QzIyOVo3ZU0wRzZ2T0Z5dDB3IiwiaWF0IjoxNjU0ODY1NjAxfQ.JslZDQ7NrdLjhoj7EvQNGfMWh953yk-k7Snz78VwRpk"
            header = {"Authorization" : api_token}
            org_list_url = BaseController.base_url +  "organization_list"
            response= requests.get(org_list_url, headers=header)
            if response.status_code != 200:
                return '0'
            else:
                data = []
                for org in response.json()["result"]:
                    temp = {}
                    temp['id'] = response.json()["result"].index(org)
                    temp['text'] = org
                    data.append(temp)
                return json.dumps(data)
        
        except:
            return 'error'