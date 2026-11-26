from datetime import datetime

import ckan.model as model

from ckanext.dataset_transfer.libs.helper import Helper
from ckanext.dataset_transfer.models.publish_api_token import PublishApiToken


class CredentialService(object):
    """Server-side access to per-user external repository credentials."""

    MASK_PREFIX = u"\u2022" * 12

    @staticmethod
    def user_from_action_context(context):
        user = context.get("auth_user_obj")
        if user:
            return user
        identity = context.get("user")
        return model.User.get(identity) if identity else None

    @staticmethod
    def record_for_user(user):
        return PublishApiToken.get_by_user(getattr(user, "id", None))

    @classmethod
    def presentation_for_user(cls, user):
        record = cls.record_for_user(user)
        token = record.api_token if record else ""
        suffix = token[-4:] if token else ""
        return {
            "repository": "luh",
            "configured": bool(token),
            "suffix": suffix,
            "masked_token": cls.MASK_PREFIX + suffix if suffix else "",
        }

    @staticmethod
    def save_for_user(user, token):
        token = token.strip() if isinstance(token, str) else ""
        if not token:
            raise ValueError("A non-empty LUH API token is required.")

        records = PublishApiToken.get_all_by_user(user.id)
        if records:
            record = records[0]
            record.api_token = token
            record.target_ckan = Helper.get_target_public_url()
            record.created_at = datetime.utcnow()
            record.save()
            for duplicate in records[1:]:
                duplicate.delete()
            if len(records) > 1:
                record.commit()
            return record

        record = PublishApiToken(
            api_token=token,
            user_id=user.id,
            target_ckan=Helper.get_target_public_url(),
            created_at=datetime.utcnow(),
        )
        record.save()
        return record

    @staticmethod
    def remove_for_user(user):
        records = PublishApiToken.get_all_by_user(user.id)
        for record in records:
            record.delete()
        if records:
            records[0].commit()
        return bool(records)

    @classmethod
    def test_for_user(cls, user, token=None):
        """Test a stored or one-request LUH token without returning it."""
        from ckanext.dataset_transfer.controllers.base import BaseController, RemoteAPIError

        candidate = token.strip() if isinstance(token, str) else ""
        if not candidate:
            record = cls.record_for_user(user)
            candidate = record.api_token.strip() if record and record.api_token else ""
        if not candidate:
            return {
                "repository": "luh", "valid": False,
                "error": "credential_missing",
                "message": "No LUH destination API token is configured.",
            }
        organization = Helper.get_organization_id()
        if not organization:
            return {
                "repository": "luh", "valid": False,
                "error": "destination_not_configured",
                "message": "The LUH destination organization is not configured.",
            }
        headers = {"Authorization": candidate}
        try:
            organization_result = BaseController._remote_json(
                "get", "organization_show", headers=headers, params={"id": organization}
            ).get("result") or {}
            authorized = BaseController._remote_json(
                "get", "organization_list_for_user", headers=headers,
                params={"permission": "create_dataset"},
            ).get("result") or []
        except RemoteAPIError:
            return {
                "repository": "luh", "valid": False,
                "error": "connection_failed",
                "message": "LUH connection failed. Verify the token and destination configuration.",
            }
        allowed_ids = {
            item.get("id") for item in authorized if isinstance(item, dict)
        } | {
            item.get("name") for item in authorized if isinstance(item, dict)
        }
        if organization_result.get("id") not in allowed_ids and organization_result.get("name") not in allowed_ids:
            return {
                "repository": "luh", "valid": False,
                "error": "insufficient_permission",
                "message": "The token cannot create datasets in the configured LUH organization.",
            }
        return {
            "repository": "luh", "valid": True,
            "organization": {
                "id": organization_result.get("id") or organization_result.get("name"),
                "name": organization_result.get("title") or organization_result.get("name") or organization,
            },
        }
