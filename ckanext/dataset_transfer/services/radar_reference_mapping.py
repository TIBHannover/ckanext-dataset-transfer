# encoding: utf-8

import logging
import re
from html.parser import HTMLParser
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


def get_ckan_reference_descriptions(dataset):
    """Load dataset-reference rows as RADAR ``Description/Other`` entries."""
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
        log.exception(
            "RADAR reference mapping import failed package_name=%s",
            package_name,
        )
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
        log.exception(
            "RADAR reference mapping query failed package_name=%s",
            package_name,
        )
        raise

    # The extension returns sqlalchemy.sql.expression.false (the function)
    # when no rows exist, so only a concrete list/tuple represents references.
    if not isinstance(references, (list, tuple)):
        return []

    descriptions = []
    seen = set()
    for reference in references:
        description = _reference_description(reference)
        if not description:
            log.warning(
                "RADAR reference skipped package_name=%s reference_id=%s title=%r reason=no_usable_metadata",
                package_name,
                getattr(reference, "id", None),
                getattr(reference, "title", "") or "",
            )
            continue
        doi = normalize_doi(getattr(reference, "doi", ""))
        url = _text(getattr(reference, "url", ""))
        reference_id = getattr(reference, "id", None)
        duplicate_key = (
            ("doi", doi.casefold()) if doi
            else ("url", url.casefold()) if _valid_http_url(url)
            else ("id", str(reference_id)) if reference_id is not None
            else ("description", description.casefold())
        )
        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)
        descriptions.append({
            "value": description,
            "type": "Other",
            "source": "dataset_reference",
            "source_reference_id": getattr(reference, "id", None),
            "fixed": True,
        })
    return descriptions


def _reference_description(reference):
    doi = normalize_doi(getattr(reference, "doi", ""))
    url = _text(getattr(reference, "url", ""))
    identifier = "doi:{}".format(doi) if doi else url if _valid_http_url(url) else ""

    # Keep the requested bibliographic order and omit absent values rather than
    # manufacturing empty publication metadata.
    structured = [
        _plain_text(getattr(reference, "authors", "")),
        _plain_text(getattr(reference, "year", "")),
        _plain_text(
            getattr(reference, "journal", "")
            or getattr(reference, "proceeding", "")
        ),
        _plain_text(getattr(reference, "volume", "")),
        _plain_text(
            getattr(reference, "page", "")
            or getattr(reference, "issue", "")
        ),
    ]
    structured = [value for value in structured if value]
    if structured:
        if identifier and not _contains_identifier("|".join(structured), doi, url):
            structured.append(identifier)
        return "Related Article: {}".format("|".join(structured))

    citation = _plain_text(getattr(reference, "citation", ""))
    if citation:
        result = "Related Article: {}".format(citation)
        if identifier and not _contains_identifier(citation, doi, url):
            result += " | {}".format(identifier)
        return result

    title = _plain_text(getattr(reference, "title", ""))
    values = [value for value in (title, identifier) if value]
    return "Related Article: {}".format(" | ".join(values)) if values else ""


def _contains_identifier(value, doi, url):
    normalized = value.casefold()
    return bool(
        (doi and doi.casefold() in normalized)
        or (url and url.casefold() in normalized)
    )


class _PlainTextParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.ignored_depth += 1
        elif tag in ("br", "div", "li", "p") and not self.ignored_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style") and self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in ("div", "li", "p") and not self.ignored_depth:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def _plain_text(value):
    parser = _PlainTextParser()
    parser.feed(_text(value))
    parser.close()
    return " ".join("".join(parser.parts).split())


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
