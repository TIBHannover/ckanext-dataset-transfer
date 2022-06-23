# encoding: utf-8

import json
import requests
from ckanext.dataset_transfer.libs.helper import Helper
from flask import request, render_template
import ckan.plugins.toolkit as toolkit


class BaseController():

    base_url = "https://data-neu.uni-hannover.de/api/3/action/"


    def publish_page(dataset_name):
        '''
            Render the publish page.
        '''
        package = toolkit.get_action('package_show')({}, {'name_or_id': dataset_name})

        return render_template('publish_page.html', pkg_dict=package)




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
                    temp['value'] = response.json()["result"].index(org)
                    temp['text'] = org
                    data.append(temp)
                return json.dumps(data)
        
        except:
            return 'error'