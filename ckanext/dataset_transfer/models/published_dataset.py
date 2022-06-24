# encoding: utf-8

import datetime
from sqlalchemy import Column, Table, ForeignKey, orm
from sqlalchemy import types as _types
from sqlalchemy.sql.expression import false
from ckan.model import meta, Resource, domain_object


__all__ = [u"PublishedDataset", u"published_dataset_table"]

published_dataset_table = Table(
    u"published_dataset",
    meta.metadata,
    Column(u"id", _types.Integer, primary_key=True, nullable=False),
    Column(u"dataset_id", _types.UnicodeText,  nullable=False),
    Column(u"doi", _types.UnicodeText, nullable=False),
    Column(u"published_url", _types.UnicodeText),
    Column(u"publish_time", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
    Column(u"publlished_dataset_id", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
)

class PublishedDataset(domain_object.DomainObject):
    def __init__(self, resource_id=None, sample_url=None, sample_name=None, create_at=None, updated_at=None):
        self.resource_id = resource_id
        self.sample_url = sample_url
        self.sample_name = sample_name
        self.create_at = create_at
        self.updated_at = updated_at
    
    @classmethod
    def get_by_resource_sample(cls, id, sample_url, autoflush=True):
        if not id:
            return None

        exists = meta.Session.query(cls).filter(cls.resource_id==id, cls.sample_url == sample_url).first() is not None
        if not exists:
            return False
        query = meta.Session.query(cls).filter(cls.resource_id==id)
        query = query.autoflush(autoflush)
        record = query.first()
        return record
    

    @classmethod
    def get_by_resource(cls, id, autoflush=True):
        if not id:
            return None

        exists = meta.Session.query(cls).filter(cls.resource_id==id).first() is not None
        if not exists:
            return False
        query = meta.Session.query(cls).filter(cls.resource_id==id)
        query = query.autoflush(autoflush)
        record = query
        return record

    
    def get_resource(self):
        return self.resource



meta.mapper(
    ResourceSampleLink,
    resource_sample_link_table,
    properties={
        u"resource": orm.relation(
            Resource, backref=orm.backref(u"resource_sample_link", cascade=u"all, delete, delete-orphan")
        )
    },
)
