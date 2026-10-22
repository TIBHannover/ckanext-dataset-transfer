# encoding: utf-8

import logging
import re
from urllib.parse import urlsplit

from ckan.model import meta
from sqlalchemy.exc import OperationalError, ProgrammingError


log = logging.getLogger(__name__)

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
DOI_URL_PATTERN = re.compile(
    r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$",
    re.IGNORECASE,
)


def normalize_doi(value):
    """Return a bare DOI while preserving the suffix spelling and punctuation."""
    value = _text(value)
    if not value:
        return ""

    url_match = DOI_URL_PATTERN.match(value)
    if url_match:
        return url_match.group(1)

    if value.lower().startswith("doi:"):
        value = value[4:].strip()

    return value if DOI_PATTERN.match(value) else ""


def get_ckan_related_identifiers(dataset):
    """Load dataset-reference rows and map them to RADAR related identifiers."""
    package_name = _text((dataset or {}).get("name"))
    if not package_name:
        log.warning("RADAR reference mapping skipped: CKAN dataset name is missing")
        return []

    try:
        from ckanext.dataset_reference.models.package_reference_link import (
            PackageReferenceLink,
        )
    except ImportError as error:
        missing_module = getattr(error, "name", "") or ""
        if missing_module.startswith("ckanext.dataset_reference"):
            log.info(
                "RADAR reference mapping unavailable package_name=%s reason=extension_not_installed",
                package_name,
            )
            return []
        raise

    try:
        references = PackageReferenceLink.get_by_package(package_name)
    except (OperationalError, ProgrammingError) as error:
        meta.Session.rollback()
        if _is_missing_reference_table(error):
            log.warning(
                "RADAR reference mapping unavailable package_name=%s reason=table_missing",
                package_name,
            )
            return []
        raise

    # The extension returns sqlalchemy.sql.expression.false (the function)
    # when no rows exist, so only a concrete list/tuple represents references.
    if not isinstance(references, (list, tuple)):
        return []

    related_identifiers = []
    for reference in references:
        doi = normalize_doi(getattr(reference, "doi", ""))
        url = _text(getattr(reference, "url", ""))
        if doi:
            related_identifiers.append({
                "value": doi,
                "identifier_type": "DOI",
                "relation_type": "",
            })
        elif _valid_http_url(url):
            related_identifiers.append({
                "value": url,
                "identifier_type": "URL",
                "relation_type": "",
            })
        else:
            log.warning(
                "RADAR reference skipped package_name=%s reference_id=%s title=%r reason=no_valid_identifier",
                package_name,
                getattr(reference, "id", None),
                getattr(reference, "title", "") or "",
            )
    return related_identifiers


def _valid_http_url(value):
    if not value or re.search(r"\s", value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)


def _is_missing_reference_table(error):
    message = str(error).lower()
    return "package_reference_link" in message and any(
        marker in message
        for marker in ("does not exist", "no such table", "undefined table")
    )


def _text(value):
    return "" if value is None else str(value).strip()
