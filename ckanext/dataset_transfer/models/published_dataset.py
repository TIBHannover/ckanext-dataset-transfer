# encoding: utf-8

import datetime
from sqlalchemy import Column, Table
from sqlalchemy import types as _types
from ckan.model import meta, domain_object


__all__ = [u"PublishedDataset", u"published_dataset_table"]

published_dataset_table = Table(
    u"published_dataset",
    meta.metadata,
    Column(u"id", _types.Integer, primary_key=True, nullable=False),
    Column(u"dataset_id", _types.UnicodeText,  nullable=False),
    Column(u"doi", _types.UnicodeText, nullable=False),
    Column(u"published_url", _types.UnicodeText, nullable=False),
    Column(u"publish_time", _types.DateTime, default=datetime.datetime.utcnow, nullable=False),
    Column(u"published_dataset_id",  _types.UnicodeText, nullable=False),
)

class PublishedDataset(domain_object.DomainObject):
    def __init__(self, dataset_id=None, doi=None, published_url=None, publish_time=None, published_dataset_id=None):
        self.dataset_id = dataset_id
        self.doi = doi
        self.published_url = published_url
        self.publish_time = publish_time
        self.published_dataset_id = published_dataset_id
    
    

    @classmethod
    def get_by_dataset(cls, id, autoflush=True):
        if not id:
            return None

        exists = meta.Session.query(cls).filter(cls.dataset_id==id).first() is not None
        if not exists:
            return False
        query = meta.Session.query(cls).filter(cls.dataset_id==id)
        query = query.autoflush(autoflush)
        record = query
        return record



meta.mapper(
    PublishedDataset,
    published_dataset_table
)
