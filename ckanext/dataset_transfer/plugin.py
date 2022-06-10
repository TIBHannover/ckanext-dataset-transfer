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
        toolkit.add_resource('fanstatic',
            'dataset_transfer')
    


    #plugin Blueprint

    def get_blueprint(self):

        blueprint = Blueprint(self.name, self.__module__)
        blueprint.template_folder = u'templates'
        blueprint.add_url_rule(
            u'/dataset_transfer/index',
            u'index',
            BaseController.index,
            methods=['GET']
            )

        return blueprint
