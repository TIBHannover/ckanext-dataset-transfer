import imp

from regex import B
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from flask import Blueprint
from ckanext.dataset_transfer.controllers.base import BaseController


class DatasetTransferPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('public', 'ckanext-dataset-transfer')
    


    #plugin Blueprint

    def get_blueprint(self):

        blueprint = Blueprint(self.name, self.__module__)
        blueprint.template_folder = u'templates'

        blueprint.add_url_rule(
            u'/dataset_transfer/publish_page/<dataset_name>',
            u'publish_page',
            BaseController.publish_page,
            methods=['GET']
            )

        blueprint.add_url_rule(
            u'/dataset_transfer/load_publish_form_data',
            u'load_publish_form_data',
            BaseController.load_publish_form_data,
            methods=['POST']
            )
        
        blueprint.add_url_rule(
            u'/dataset_transfer/publish',
            u'publish',
            BaseController.publish,
            methods=['POST']
            )
        
        blueprint.add_url_rule(
            u'/dataset_transfer/user_has_api_token',
            u'user_has_api_token',
            BaseController.user_has_api_token,
            methods=['GET']
            )

        return blueprint


    def get_helpers(self):
        return {'is_dataset_published': BaseController.is_dataset_published}