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
