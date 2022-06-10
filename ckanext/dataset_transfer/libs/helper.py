# encoding: utf-8

import ckan.plugins.toolkit as toolkit


class Helper():


    '''
        check the user can publish a dataset or not. The user who can edit the target dataset, also 
        can publish it.
    '''
    def check_access_edit_package(package_id):
        context = {'user': toolkit.g.user, 'auth_user_obj': toolkit.g.userobj}
        data_dict = {'id':package_id}
        try:
            toolkit.check_access('package_update', context, data_dict)
            return True

        except toolkit.NotAuthorized:
            return False
            