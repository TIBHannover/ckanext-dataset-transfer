# encoding: utf-8

from email import header
import requests
from ckanext.dataset_transfer.libs.helper import Helper


class BaseController():

    base_url = "https://data-neu.uni-hannover.de/api/3/action/"

    def load_publish_form_data(package_id):
        try:
            if not Helper.check_access_edit_package(package_id):
                return 'Not Authorized'
            
            header = {"Authorization" : "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJqdGkiOiJhUkZXRkZkUEtEYkVtUHREY2FYdDFpeWh2QzIyOVo3ZU0wRzZ2T0Z5dDB3IiwiaWF0IjoxNjU0ODY1NjAxfQ.JslZDQ7NrdLjhoj7EvQNGfMWh953yk-k7Snz78VwRpk"}
            org_list_url = BaseController.base_url +  "organization_list"
            response= requests.get(org_list_url, headers=header)
            if response.status_code != 200:
                return '0'
            else:
                return response.json()["result"]
        
        except:
            return 'error'