import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime

import ckan.plugins.toolkit as toolkit

from ckanext.dataset_transfer.services.radar import (
    RadarConfigError,
    RadarPublishError,
    RadarPublisher,
    RadarStatusError,
)
from ckanext.dataset_transfer.services.radar_auth import (
    RadarAuthConfigError,
    RadarAuthenticationError,
    RadarTokenProvider,
)


log = logging.getLogger(__name__)


class RadarStatusService(object):
    """Short-lived, process-local cache for read-only RADAR lifecycle lookups."""

    DEFAULT_TTL = 300
    MAX_CACHE_ENTRIES = 512
    _cache = OrderedDict()
    _lock = threading.Lock()

    @classmethod
    def lookup(cls, dataset_id, refresh=False):
        context_url = str(
            toolkit.config.get("ckanext.dataset_transfer.radar.context_url") or ""
        ).rstrip("/")
        cache_key = (context_url, dataset_id)
        now = time.monotonic()
        ttl = cls._cache_ttl()
        with cls._lock:
            cached = cls._cache.get(cache_key)
            if cached and not refresh and now - cached["cached_at"] < ttl:
                cls._cache.move_to_end(cache_key)
                result = dict(cached["result"])
                result["repository_status_source"] = "cache"
                return result

        checked_at = cls._utc_now()
        try:
            publisher = RadarPublisher(
                config=toolkit.config,
                token_provider=RadarTokenProvider(toolkit.config),
            )
            result = publisher.get_dataset_status(dataset_id)
        except RadarStatusError as error:
            return cls._unavailable(cache_key, cached, checked_at, error.code)
        except RadarAuthenticationError:
            return cls._unavailable(
                cache_key, cached, checked_at, "authentication_failed"
            )
        except (RadarConfigError, RadarAuthConfigError):
            return cls._unavailable(cache_key, cached, checked_at, "configuration")
        except RadarPublishError:
            return cls._unavailable(
                cache_key, cached, checked_at, "authentication_failed"
            )
        except Exception:
            # Do not log exception text: third-party exceptions may contain a token
            # or response body. The dataset id is the locally persisted identifier.
            log.warning("Unexpected RADAR status lookup failure dataset_id=%s", dataset_id)
            return cls._unavailable(
                cache_key, cached, checked_at, "service_unavailable"
            )

        result.update({
            "repository_status_available": True,
            "repository_status_source": "radar_api",
            "repository_status_checked_at": checked_at,
            "repository_status_error": None,
        })
        entry = {"cached_at": now, "result": dict(result)}
        with cls._lock:
            cls._cache[cache_key] = entry
            cls._cache.move_to_end(cache_key)
            while len(cls._cache) > cls.MAX_CACHE_ENTRIES:
                cls._cache.popitem(last=False)
        return result

    @classmethod
    def _unavailable(cls, cache_key, cached, checked_at, error_code):
        if cached:
            result = dict(cached["result"])
            result.update({
                "repository_status_available": False,
                "repository_status_source": "stale_cache",
                "repository_status_error": error_code,
            })
            return result
        return {
            "repository_status": None,
            "repository_status_raw": None,
            "repository_status_label": "Temporarily unavailable",
            "repository_status_available": False,
            "repository_status_source": "unavailable",
            "repository_status_checked_at": checked_at,
            "repository_status_error": error_code,
        }

    @classmethod
    def _cache_ttl(cls):
        value = toolkit.config.get(
            "ckanext.dataset_transfer.radar.status_cache_ttl", cls.DEFAULT_TTL
        )
        try:
            return max(float(value), 0)
        except (TypeError, ValueError):
            return cls.DEFAULT_TTL

    @staticmethod
    def _utc_now():
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    @classmethod
    def clear_cache(cls):
        """Clear process-local entries (primarily for tests and reloads)."""
        with cls._lock:
            cls._cache.clear()
