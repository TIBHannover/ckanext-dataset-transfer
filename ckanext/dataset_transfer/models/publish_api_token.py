# encoding: utf-8

import datetime
from sqlalchemy import Column, Table, ForeignKey, orm
from sqlalchemy import types as _types
from ckan.model import meta, domain_object, User


__all__ = [u"PublishApiToken", u"publish_api_token_table"]

publish_api_token_table = Table(
    u"publish_api_token",
    meta.metadata,
    Column(u"id", _types.Integer, primary_key=True, nullable=False),
    Column(u"api_token", _types.UnicodeText,  nullable=False),
    Column(u"user_id", _types.UnicodeText, ForeignKey(u"user.id"), nullable=False),
    Column(u"target_ckan", _types.UnicodeText, nullable=False),
    Column(u"created_at", _types.DateTime, default=datetime.datetime.utcnow, nullable=False)
)

class PublishApiToken(domain_object.DomainObject):
    def __init__(self, api_token=None, user_id=None, target_ckan=None, created_at=None):
        self.api_token = api_token
        self.user_id = user_id
        self.target_ckan = target_ckan
        self.created_at = created_at
    
    

    @classmethod
    def get_by_user(cls, id, autoflush=True):
        if not id:
            return None

        exists = meta.Session.query(cls).filter(cls.user_id==id).first() is not None
        if not exists:
            return False
        query = meta.Session.query(cls).filter(cls.user_id==id)
        query = query.autoflush(autoflush)
        record = query.first()
        return record



meta.mapper(
    PublishApiToken,
    publish_api_token_table,
    properties={
        u"user": orm.relationship(
            User, backref=orm.backref(u"publish_api_token", cascade=u"all, delete, delete-orphan")
        )
    },
)
