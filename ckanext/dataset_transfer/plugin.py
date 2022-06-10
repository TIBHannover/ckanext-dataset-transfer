import imp
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from flask import Blueprint
from ckanext.dataset_transfer.controllers.base import BaseController


class DatasetTransferPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)

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
            u'/dataset_transfer/load_publish_form_data/<package_id>',
            u'load_publish_form_data',
            BaseController.load_publish_form_data,
            methods=['GET']
            )

        return blueprint
