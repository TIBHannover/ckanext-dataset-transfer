# encoding: utf-8

import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Table, UniqueConstraint, orm
from sqlalchemy import types as _types

from ckan.model import User, domain_object, meta


__all__ = [
    u"RadarOAuthToken",
    u"RadarOAuthState",
    u"radar_oauth_token_table",
    u"radar_oauth_state_table",
]


radar_oauth_token_table = Table(
    u"radar_oauth_token",
    meta.metadata,
    Column(u"id", Integer, primary_key=True, nullable=False),
    Column(u"ckan_user_id", _types.UnicodeText, ForeignKey(u"user.id"), nullable=False),
    Column(u"radar_environment", _types.UnicodeText, nullable=False),
    Column(u"access_token_encrypted", _types.UnicodeText, nullable=False),
    Column(u"refresh_token_encrypted", _types.UnicodeText, nullable=True),
    Column(u"expires_at", _types.DateTime, nullable=False),
    Column(u"connected_at", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
    Column(u"updated_at", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
    Column(u"requires_reauthentication", Boolean, default=False, nullable=False),
    UniqueConstraint(
        u"ckan_user_id",
        u"radar_environment",
        name=u"uq_radar_oauth_token_user_environment",
    ),
)


radar_oauth_state_table = Table(
    u"radar_oauth_state",
    meta.metadata,
    Column(u"id", Integer, primary_key=True, nullable=False),
    Column(u"ckan_user_id", _types.UnicodeText, ForeignKey(u"user.id"), nullable=False),
    Column(u"radar_environment", _types.UnicodeText, nullable=False),
    Column(u"state_hash", _types.UnicodeText, nullable=False, unique=True),
    Column(u"session_binding_hash", _types.UnicodeText, nullable=False),
    Column(u"code_verifier_encrypted", _types.UnicodeText, nullable=True),
    Column(u"dataset_name", _types.UnicodeText, nullable=False),
    Column(u"created_at", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
    Column(u"used_at", _types.DateTime, nullable=True),
)


class RadarOAuthToken(domain_object.DomainObject):
    def __init__(
        self,
        ckan_user_id=None,
        radar_environment=None,
        access_token_encrypted=None,
        refresh_token_encrypted=None,
        expires_at=None,
        connected_at=None,
        updated_at=None,
        requires_reauthentication=False,
    ):
        self.ckan_user_id = ckan_user_id
        self.radar_environment = radar_environment
        self.access_token_encrypted = access_token_encrypted
        self.refresh_token_encrypted = refresh_token_encrypted
        self.expires_at = expires_at
        self.connected_at = connected_at
        self.updated_at = updated_at
        self.requires_reauthentication = requires_reauthentication

    @classmethod
    def get_by_user_environment(
        cls, user_id, radar_environment, autoflush=True, for_update=False
    ):
        if not user_id or not radar_environment:
            return None
        query = meta.Session.query(cls).filter(
            cls.ckan_user_id == user_id,
            cls.radar_environment == radar_environment,
        ).autoflush(autoflush)
        if for_update:
            query = query.with_for_update()
        return query.first()


class RadarOAuthState(domain_object.DomainObject):
    def __init__(
        self,
        ckan_user_id=None,
        radar_environment=None,
        state_hash=None,
        session_binding_hash=None,
        code_verifier_encrypted=None,
        dataset_name=None,
        created_at=None,
        used_at=None,
    ):
        self.ckan_user_id = ckan_user_id
        self.radar_environment = radar_environment
        self.state_hash = state_hash
        self.session_binding_hash = session_binding_hash
        self.code_verifier_encrypted = code_verifier_encrypted
        self.dataset_name = dataset_name
        self.created_at = created_at
        self.used_at = used_at

    @classmethod
    def get_by_state_hash(cls, state_hash, autoflush=True, for_update=False):
        if not state_hash:
            return None
        query = meta.Session.query(cls).filter(
            cls.state_hash == state_hash
        ).autoflush(autoflush)
        if for_update:
            query = query.with_for_update()
        return query.first()

    @classmethod
    def delete_open_for_user(cls, user_id, radar_environment):
        meta.Session.query(cls).filter(
            cls.ckan_user_id == user_id,
            cls.radar_environment == radar_environment,
            cls.used_at.is_(None),
        ).delete(synchronize_session=False)


meta.mapper(
    RadarOAuthToken,
    radar_oauth_token_table,
    properties={
        u"user": orm.relationship(
            User,
            foreign_keys=[radar_oauth_token_table.c.ckan_user_id],
        )
    },
)

meta.mapper(
    RadarOAuthState,
    radar_oauth_state_table,
    properties={
        u"user": orm.relationship(
            User,
            foreign_keys=[radar_oauth_state_table.c.ckan_user_id],
        )
    },
)
