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
    TARGET_ID_PREFIX = u"dataset-transfer-target:"
    RADAR_INCOMPLETE_PREFIX = u"dataset-transfer-radar-incomplete:"

    def __init__(self, dataset_id=None, doi=None, published_url=None, publish_time=None,
                 published_dataset_id=None):
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
        record = query.first()
        return record

    @classmethod
    def get_by_dataset_and_target(cls, id, target, autoflush=True):
        if not id or target not in (u"luh", u"radar"):
            return None
        # Store the target alongside the remote identifier in the existing column.
        # This avoids a database migration while keeping new records unambiguous.
        return meta.Session.query(cls).filter(
            cls.dataset_id == id,
            cls.published_dataset_id.like(cls.target_prefix(target) + u"%"),
        ).autoflush(autoflush).first()

    @classmethod
    def get_incomplete_radar_transfer(cls, id, autoflush=True):
        if not id:
            return None
        return meta.Session.query(cls).filter(
            cls.dataset_id == id,
            cls.published_dataset_id.like(cls.RADAR_INCOMPLETE_PREFIX + u"%"),
        ).autoflush(autoflush).first()

    @classmethod
    def get_all_by_dataset(cls, id, autoflush=True):
        if not id:
            return []
        return meta.Session.query(cls).filter(
            cls.dataset_id == id
        ).order_by(cls.publish_time.asc()).autoflush(autoflush).all()

    @classmethod
    def target_prefix(cls, target):
        return cls.TARGET_ID_PREFIX + target + u":"

    @classmethod
    def encode_target_id(cls, target, published_dataset_id):
        if target not in (u"luh", u"radar"):
            raise ValueError("Unsupported repository target")
        return cls.target_prefix(target) + (published_dataset_id or u"")

    @classmethod
    def decode_target_id(cls, value):
        value = value or u""
        for target in (u"luh", u"radar"):
            prefix = cls.target_prefix(target)
            if value.startswith(prefix):
                return target, value[len(prefix):]
        return None, value

    @classmethod
    def encode_incomplete_radar_id(cls, status, published_dataset_id):
        return cls.RADAR_INCOMPLETE_PREFIX + status + u":" + (
            published_dataset_id or u""
        )

    @classmethod
    def decode_incomplete_radar_id(cls, value):
        value = value or u""
        if not value.startswith(cls.RADAR_INCOMPLETE_PREFIX):
            return None
        remainder = value[len(cls.RADAR_INCOMPLETE_PREFIX):]
        status, separator, published_dataset_id = remainder.partition(u":")
        if not separator:
            return None
        return {
            "status": status,
            "published_dataset_id": published_dataset_id,
        }



meta.mapper(
    PublishedDataset,
    published_dataset_table
)
