# encoding: utf-8

import queue
from threading import Thread

import requests
import ckan.plugins.toolkit as toolkit


class Helper():


    '''
        check the user can publish a dataset or not. The user who can edit the target dataset, also 
        can publish it.
    '''
    def check_access_edit_package(package_id):
        user = toolkit.current_user
        context = {'user': user.name, 'auth_user_obj': user}
        data_dict = {'id':package_id}
        try:
            toolkit.check_access('package_update', context, data_dict)
            return True

        except toolkit.NotAuthorized:
            return False
    


    def upload_data_resources(resources, target_dataset_id, base_url, headers, api_token):
        '''
            Upload the data resources in to a target dataset via ckan API.
            Used Threading/queue for sake of speed improvement.
        '''

        # number_of_workers = len(resources)
        number_of_workers = 16
        resources_dir_path = toolkit.config['ckan.storage_path'] + '/resources/'
        
        class Worker(Thread):
            def __init__(self, request_queue):
                Thread.__init__(self)
                self.queue = request_queue
                self.results = []
            
            def run(self):
                while True:
                    resource = self.queue.get()
                    if resource == "":
                        break
                    
                    headers["Content-Type"] = "application/json"
                    if resource['url_type'] == 'upload':
                        resource_data = resource.copy()
                        file_content = {'upload': ''}
                        resource_data['package_id'] = target_dataset_id
                        file_path = resources_dir_path + resource['id'][0:3] + '/' + resource['id'][3:6] + '/' + resource['id'][6:]
                        with open(file_path, 'rb') as file:
                            file_content['upload'] = file.read()

                        created_resource = requests.post(base_url + "resource_create", headers=headers, json=resource_data)
                        if created_resource.status_code == 200 and 'id' in created_resource.json()['result']:
                            # upload the data file
                            resource_patch_headers = {'Authorization' : api_token.strip()}
                            res_data = {"id": created_resource.json()['result']['id']} 
                            uploaded_file = requests.post(base_url + "resource_patch", data=res_data, headers=resource_patch_headers, files=file_content)                    
                            # self.results.append(uploaded_file.status_code)
                            self.queue.task_done()
                        
                        self.results.append(created_resource.status_code)
                        self.queue.task_done()
                    
                    else:
                        resource_data = resource.copy()
                        resource_data['package_id'] = target_dataset_id
                        created_resource = requests.post(base_url + "resource_create", headers=headers, json=resource_data)
                        self.results.append(created_resource.status_code)
                        self.queue.task_done()
                    

        q = queue.Queue()
        for res in resources:
            q.put(res)
        
        for _ in range(number_of_workers):
            q.put("")
        
        workers = []
        for _ in range(number_of_workers):
            worker = Worker(q)
            worker.start()
            workers.append(worker)
        
        for worker in workers:
            worker.join()
        
        all_results = []
        for worker in workers:
            all_results.extend(worker.results)
        
        return all_results



    def get_organization_id():
        ckan_root_path = toolkit.config.get('ckan.root_path')
        if  ckan_root_path and 'sfb1368/ckan' in ckan_root_path:
            return "sfb_1368"
        elif ckan_root_path and 'sfb1153/ckan' in ckan_root_path:
            return "sfb_1153"
        else:
            return "" 
                    


            
