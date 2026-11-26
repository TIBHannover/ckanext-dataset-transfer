import logging

import ckan.plugins.toolkit as toolkit
from flask import current_app, redirect, render_template, request
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from ckanext.dataset_transfer.services.credentials import CredentialService


log = logging.getLogger(__name__)


class CredentialsController(object):

    @staticmethod
    def _current_user():
        user = toolkit.current_user
        if not user or getattr(user, "is_anonymous", False) or not getattr(user, "name", None):
            toolkit.abort(403, "Authentication required")
        return user

    @staticmethod
    def _csrf_protect():
        field = current_app.config.get("WTF_CSRF_FIELD_NAME", "csrf_token")
        token = request.form.get(field)
        try:
            validate_csrf(token)
        except ValidationError:
            toolkit.abort(400, "Invalid CSRF token")

    @classmethod
    def page(cls):
        user = cls._current_user()
        user_dict = toolkit.get_action("user_show")(
            {"user": user.name, "auth_user_obj": user},
            {
                "id": user.name,
                "include_datasets": True,
                "include_num_followers": True,
            },
        )
        return render_template(
            "user/external_api_tokens.html",
            user_dict=user_dict,
            is_myself=True,
            is_sysadmin=bool(getattr(user, "sysadmin", False)),
            about_formatted=toolkit.h.render_markdown(user_dict.get("about") or ""),
            am_following=False,
            credential=CredentialService.presentation_for_user(user),
        )

    @classmethod
    def save(cls):
        user = cls._current_user()
        cls._csrf_protect()
        try:
            CredentialService.save_for_user(user, request.form.get("luh_api_token"))
        except ValueError as error:
            toolkit.h.flash_error(str(error))
        else:
            toolkit.h.flash_success("LUH API token saved.")
        return redirect(toolkit.url_for("dataset_transfer.credentials"))

    @classmethod
    def remove(cls):
        user = cls._current_user()
        cls._csrf_protect()
        CredentialService.remove_for_user(user)
        toolkit.h.flash_success("LUH API token removed.")
        return redirect(toolkit.url_for("dataset_transfer.credentials"))

    @classmethod
    def test_connection(cls):
        user = cls._current_user()
        cls._csrf_protect()
        result = CredentialService.test_for_user(user)
        if not result["valid"]:
            log.warning("LUH credential connection test failed user_id=%s", user.id)
            toolkit.h.flash_error(result["message"])
        else:
            toolkit.h.flash_success(
                "LUH connection successful. Destination organization: {}".format(
                    result["organization"]["name"]
                )
            )
        return redirect(toolkit.url_for("dataset_transfer.credentials"))
