# encoding: utf-8

import copy
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET


SUBJECT_AREAS = (
    "Agriculture", "Architecture", "Arts and Media", "Astrophysics and Astronomy",
    "Biochemistry", "Biology", "Behavioural Sciences", "Chemistry", "Computer Science",
    "Economics", "Engineering", "Environmental Science and Ecology", "Ethnology",
    "Geological Science", "Geography", "History", "Horticulture",
    "Information Technology", "Linguistics", "Life Science", "Materials Science",
    "Mathematics", "Medicine", "Philosophy", "Physics", "Psychology",
    "Social Sciences", "Software Technology", "Sports", "Theology",
    "Veterinary Medicine", "Other",
)
RESOURCE_TYPES = (
    "Audiovisual", "Collection", "ComputationalNotebook", "DataPaper", "Dataset",
    "Event", "Image", "InteractiveResource", "Instrument", "Model", "PhysicalObject",
    "Project", "Service", "Software", "Sound", "Standard", "Text", "Workflow", "Other",
)
RIGHTS = (
    "CC BY 4.0 Attribution", "CC BY-ND 4.0 Attribution-NoDerivs",
    "CC BY-SA 4.0 Attribution-ShareAlike", "CC BY-NC 4.0 Attribution-NonCommercial",
    "CC BY-NC-SA 4.0 Attribution-NonCommercial-ShareAlike",
    "CC BY-NC-ND 4.0 Attribution-NonCommercial-NoDerivs",
    "CC0 1.0 Universal Public Domain Dedication", "Public Domain Mark 1.0",
    "Public Domain Dedication and License (PDDL)", "Attribution License (ODC-By)",
    "Open Database License (ODC-ODbL)", "Apache License 2.0",
    "Common Development and Distribution License 1.0", "Eclipse Public License 1.0",
    "Eclipse Public License 2.0", "GNU General Public License v3.0 only",
    "GNU Lesser General Public License v3.0 only", "BSD 2-Clause Simplified License",
    "BSD 3-Clause New or Revised License", "MIT License", "All rights reserved", "Other",
)
CONTRIBUTOR_TYPES = (
    "ContactPerson", "DataCollector", "DataCurator", "DataManager", "Distributor", "Editor",
    "HostingInstitution", "Producer", "ProjectLeader", "ProjectManager", "ProjectMember",
    "RegistrationAgency", "RegistrationAuthority", "RelatedPerson", "Researcher",
    "ResearchGroup", "Sponsor", "Supervisor", "Translator", "WorkPackageLeader", "Other",
)
ADDITIONAL_TITLE_TYPES = ("Subtitle", "TranslatedTitle", "AlternativeTitle", "Other")
DESCRIPTION_TYPES = (
    "Abstract", "Object", "Method", "TableOfContents", "TechnicalInfo",
    "TechnicalRemarks", "VersionNotes", "Other",
)
RELATED_IDENTIFIER_TYPES = (
    "ARK", "arXiv", "bibcode", "CSTR", "DOI", "EAN13", "EISSN", "Handle", "ePIC",
    "IGSN", "ISBN", "ISSN", "ISTC", "LISSN", "LSID", "PMID", "PURL", "RAiD",
    "RRID", "SWHID", "UPC", "URL", "URN", "w3id",
)
RELATION_TYPES = (
    "IsCitedBy", "Cites", "IsSupplementTo", "IsSupplementedBy", "IsContinuedBy",
    "Continues", "Describes", "IsDescribedBy", "HasMetadata", "IsMetadataFor",
    "HasVersion", "IsVersionOf", "IsNewVersionOf", "IsPreviousVersionOf", "IsPartOf",
    "HasPart", "IsPublishedIn", "IsReferencedBy", "References", "IsDocumentedBy",
    "Documents", "IsCompiledBy", "Compiles", "IsVariantFormOf", "IsOriginalFormOf",
    "IsIdenticalTo", "IsReviewedBy", "Reviews", "IsDerivedFrom", "IsSourceOf",
    "Requires", "IsRequiredBy", "Obsoletes", "IsObsoletedBy", "IsCollectedBy",
    "Collects", "HasTranslation", "IsTranslationOf",
)
DATA_SOURCE_TYPES = ("Instrument", "Media", "Observation", "Survey", "Trial", "Organism", "Tissue", "Other")
SOFTWARE_TYPES = ("Resource Production", "Resource Processing", "Resource Viewing", "Other")
FUNDER_IDENTIFIER_TYPES = ("CrossRefFunder", "GRID", "ISNI", "ROR", "Other")
def _language_vocabulary():
    path = Path(__file__).resolve().parent.parent / "schemas" / "radar" / "v9.3" / "RadarTypes.xsd"
    namespace = {"xs": "http://www.w3.org/2001/XMLSchema", "dc": "http://purl.org/dc/elements/1.1/"}
    try:
        root = ET.parse(str(path)).getroot()
        language_type = root.find("xs:simpleType[@name='language']", namespace)
        values = []
        for item in language_type.findall(".//xs:enumeration", namespace):
            value = item.get("value")
            label = value
            for title in item.findall(".//dc:title", namespace):
                if title.get("{http://www.w3.org/XML/1998/namespace}lang") == "en":
                    label = title.text or value
                    break
            values.append((value, label))
        if values:
            return tuple(values)
    except (AttributeError, ET.ParseError, OSError):
        pass
    return (("deu", "German"), ("eng", "English"), ("und", "Undetermined"))


LANGUAGES = (("", "Not specified"),) + _language_vocabulary()


def _xsd_values(type_name):
    path = Path(__file__).resolve().parent.parent / "schemas" / "radar" / "v9.3" / "RadarTypes.xsd"
    namespace = {"xs": "http://www.w3.org/2001/XMLSchema"}
    try:
        root = ET.parse(str(path)).getroot()
        simple_type = root.find("xs:simpleType[@name='{}']".format(type_name), namespace)
        return tuple(item.get("value") for item in simple_type.findall(".//xs:enumeration", namespace))
    except (AttributeError, ET.ParseError, OSError):
        return ()


COUNTRIES = _xsd_values("ISO3166-Country-Name")

LICENSE_MAP = {
    "cc-by-4.0": "CC BY 4.0 Attribution",
    "cc-by-nd-4.0": "CC BY-ND 4.0 Attribution-NoDerivs",
    "cc-by-sa-4.0": "CC BY-SA 4.0 Attribution-ShareAlike",
    "cc-by-nc-4.0": "CC BY-NC 4.0 Attribution-NonCommercial",
    "cc-by-nc-sa-4.0": "CC BY-NC-SA 4.0 Attribution-NonCommercial-ShareAlike",
    "cc-by-nc-nd-4.0": "CC BY-NC-ND 4.0 Attribution-NonCommercial-NoDerivs",
    "cc0-1.0": "CC0 1.0 Universal Public Domain Dedication",
    "apache-2.0": "Apache License 2.0",
    "mit": "MIT License",
}

VOCABULARIES = {
    "subject_areas": SUBJECT_AREAS,
    "resource_types": RESOURCE_TYPES,
    "rights": RIGHTS,
    "contributor_types": CONTRIBUTOR_TYPES,
    "additional_title_types": ADDITIONAL_TITLE_TYPES,
    "description_types": DESCRIPTION_TYPES,
    "related_identifier_types": RELATED_IDENTIFIER_TYPES,
    "relation_types": RELATION_TYPES,
    "data_source_types": DATA_SOURCE_TYPES,
    "software_types": SOFTWARE_TYPES,
    "funder_identifier_types": FUNDER_IDENTIFIER_TYPES,
    "languages": LANGUAGES,
    "countries": COUNTRIES,
}

LIST_FIELDS = {
    "creators", "contributors", "additional_titles", "descriptions", "keywords",
    "publishers", "subject_areas", "rights_holders", "alternate_identifiers",
    "related_identifiers", "geo_locations", "data_sources", "software",
    "data_processing", "related_information", "funding_references",
}
SCALAR_FIELDS = {"title", "production_year", "publication_year", "language", "resource_type", "resource", "rights", "additional_rights", "version"}
ALLOWED_FIELDS = LIST_FIELDS | SCALAR_FIELDS


def map_ckan_to_radar(dataset, configured_publisher=None):
    source = copy.deepcopy(dataset or {})
    organization = source.get("organization") if isinstance(source.get("organization"), dict) else {}
    organization_title = _text(organization.get("title"))
    publisher = _text(configured_publisher) or organization_title
    creators = _structured_list(source, "creators")
    if creators:
        creators = [_normalize_person(item) for item in creators if isinstance(item, dict)]
    elif _text(source.get("author")):
        creators = [{"name": _text(source.get("author")), "given_name": "", "family_name": "", "orcid": "", "affiliation": "", "affiliation_ror": ""}]

    contributors = []
    if _text(source.get("maintainer")):
        contributors.append({
            "name": _text(source.get("maintainer")), "given_name": "", "family_name": "",
            "orcid": "", "affiliation": "", "affiliation_ror": "", "type": "ContactPerson",
        })
    subject_areas = _structured_list(source, "subject_area") or _structured_list(source, "subject_areas")
    subject_areas = [_text(item.get("value") if isinstance(item, dict) else item) for item in subject_areas]
    subject_areas = [value for value in subject_areas if value in SUBJECT_AREAS]
    resource_type = _text(source.get("resource_type"))
    if resource_type not in RESOURCE_TYPES:
        resource_type = "Dataset"
    rights = LICENSE_MAP.get(_text(source.get("license_id")).lower(), "")
    keywords = []
    structured_keywords = _structured_list(source, "keywords")
    if structured_keywords:
        for item in structured_keywords:
            if isinstance(item, dict):
                keywords.append({
                    "value": _text(item.get("value") or item.get("name")),
                    "scheme": _text(item.get("scheme") or item.get("keyword_scheme")) or "Other",
                    "scheme_uri": _text(item.get("scheme_uri")), "value_uri": _text(item.get("value_uri")),
                    "classification_code": _text(item.get("classification_code")),
                    "ontology_uri": _text(item.get("ontology_uri")), "ontology_id": _text(item.get("ontology_id")),
                })
    else:
        for tag in source.get("tags") or []:
            value = _text(tag.get("display_name") or tag.get("name")) if isinstance(tag, dict) else _text(tag)
            if value:
                keywords.append({"value": value, "scheme": "Other", "scheme_uri": "", "value_uri": "", "classification_code": "", "ontology_uri": "", "ontology_id": ""})

    descriptions = [{"value": _text(source.get("notes")), "type": "Abstract"}] if _text(source.get("notes")) else []
    data_processing = []
    for resource in source.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        if _text(resource.get("analysis_method")):
            descriptions.append({"value": _text(resource.get("analysis_method")), "type": "Method"})
        if _text(resource.get("surface_preparation")):
            data_processing.append("Surface preparation: {}".format(_text(resource.get("surface_preparation"))))
        technical = []
        if _text(resource.get("atmosphere")):
            technical.append("Atmosphere: {}".format(_text(resource.get("atmosphere"))))
        if _text(resource.get("material_combination")):
            technical.append("Material combination: {}".format(_text(resource.get("material_combination"))))
        if technical:
            descriptions.append({"value": "; ".join(technical), "type": "TechnicalInfo"})

    return {
        "title": _text(source.get("title") or source.get("name")),
        "descriptions": descriptions,
        "creators": creators,
        "contributors": contributors,
        "publishers": [publisher] if publisher else [],
        "production_year": _text(source.get("production_year")),
        "publication_year": "",
        "subject_areas": subject_areas,
        "resource_type": resource_type,
        "resource": _text(source.get("resource_description") or source.get("title") or source.get("name")),
        "rights": rights,
        "additional_rights": "",
        "rights_holders": [organization_title] if organization_title else [],
        "keywords": keywords,
        "language": _normalize_language(source.get("language")),
        "version": _text(source.get("version")),
        "additional_titles": [], "alternate_identifiers": [], "related_identifiers": [],
        "geo_locations": [], "data_sources": [], "software": [], "data_processing": data_processing,
        "related_information": [], "funding_references": [],
    }


def normalize_reviewed_metadata(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = {}
    value = value if isinstance(value, dict) else {}
    normalized = {key: copy.deepcopy(value.get(key)) for key in ALLOWED_FIELDS}
    for key in SCALAR_FIELDS:
        normalized[key] = _text(normalized.get(key))
    for key in LIST_FIELDS:
        normalized[key] = normalized.get(key) if isinstance(normalized.get(key), list) else []
    normalized["creators"] = [_normalize_person(item) for item in normalized["creators"] if isinstance(item, dict)]
    normalized["contributors"] = [_normalize_contributor(item) for item in normalized["contributors"] if isinstance(item, dict)]
    for key in ("publishers", "rights_holders", "data_processing"):
        normalized[key] = [_text(item.get("value") if isinstance(item, dict) else item) for item in normalized[key]]
        normalized[key] = [item for item in normalized[key] if item]
    normalized["subject_areas"] = [_normalize_subject_area(item) for item in normalized["subject_areas"]]
    normalized["additional_titles"] = [_normalize_object(item, ("value", "type")) for item in normalized["additional_titles"] if isinstance(item, dict)]
    normalized["descriptions"] = [_normalize_object(item, ("value", "type")) for item in normalized["descriptions"] if isinstance(item, dict)]
    normalized["keywords"] = [_normalize_object(item, ("value", "scheme", "scheme_uri", "value_uri", "classification_code", "ontology_uri", "ontology_id")) for item in normalized["keywords"] if isinstance(item, dict)]
    normalized["alternate_identifiers"] = [_normalize_object(item, ("value", "type")) for item in normalized["alternate_identifiers"] if isinstance(item, dict)]
    normalized["related_identifiers"] = [_normalize_object(item, ("value", "identifier_type", "relation_type")) for item in normalized["related_identifiers"] if isinstance(item, dict)]
    normalized["geo_locations"] = [_normalize_object(item, ("country", "region", "latitude", "longitude")) for item in normalized["geo_locations"] if isinstance(item, dict)]
    normalized["data_sources"] = [_normalize_object(item, ("value", "type")) for item in normalized["data_sources"] if isinstance(item, dict)]
    normalized["software"] = [_normalize_object(item, ("name", "version", "type", "alternative_name", "alternative_version")) for item in normalized["software"] if isinstance(item, dict)]
    normalized["related_information"] = [_normalize_object(item, ("value", "type")) for item in normalized["related_information"] if isinstance(item, dict)]
    normalized["funding_references"] = [_normalize_object(item, ("funder_name", "funder_identifier", "funder_identifier_type", "funder_scheme_uri", "award_number", "award_uri", "award_title")) for item in normalized["funding_references"] if isinstance(item, dict)]
    return normalized


def validate_radar_metadata(metadata):
    data = normalize_reviewed_metadata(metadata)
    errors = []
    warnings = []
    _required(errors, "title", data["title"], "Please provide a title.")
    _required(errors, "creators", data["creators"], "Please provide at least one creator.")
    _required(errors, "publishers", data["publishers"], "Please provide at least one publisher.")
    _required(errors, "production_year", data["production_year"], "Please provide the production year.")
    _required(errors, "subject_areas", data["subject_areas"], "Please select at least one scientific subject area.")
    _required(errors, "resource_type", data["resource_type"], "Please select a resource type.")
    _required(errors, "rights", data["rights"], "Please select a licence.")
    _required(errors, "rights_holders", data["rights_holders"], "Please provide at least one rights holder.")
    if data["production_year"] and not re.match(r"^(\d{4}|\d{4}-\d{4}|unknown)$", data["production_year"]):
        _error(errors, "production_year", "Use YYYY, YYYY-YYYY, or unknown.")
    if data["publication_year"] and not re.match(r"^\d{4}$", data["publication_year"]):
        _error(errors, "publication_year", "Publication year must use YYYY.")
    if data["resource_type"] and data["resource_type"] not in RESOURCE_TYPES:
        _error(errors, "resource_type", "Please select a valid RADAR resource type.")
    if data["rights"] and data["rights"] not in RIGHTS:
        _error(errors, "rights", "Please select a valid RADAR licence.")
    if data["rights"] == "Other" and not data["additional_rights"]:
        _error(errors, "additional_rights", "Please describe the custom rights statement.")
    for index, area in enumerate(data["subject_areas"]):
        controlled = _text(area.get("controlled") if isinstance(area, dict) else area)
        additional = _text(area.get("additional") if isinstance(area, dict) else "")
        if controlled not in SUBJECT_AREAS:
            _error(errors, "subject_areas.{}".format(index), "Please select a valid RADAR subject area.")
        if controlled == "Other" and not additional:
            _error(errors, "subject_areas.{}.additional".format(index), "Please specify the additional subject area.")
    if data["language"] and data["language"] not in dict(LANGUAGES):
        _error(errors, "language", "Please select a valid RADAR language code.")
    for index, item in enumerate(data["additional_titles"]):
        if not item["value"] or item["type"] not in ADDITIONAL_TITLE_TYPES:
            _error(errors, "additional_titles.{}".format(index), "Each additional title needs text and a valid title type.")
    for index, item in enumerate(data["descriptions"]):
        if not item["value"] or item["type"] not in DESCRIPTION_TYPES:
            _error(errors, "descriptions.{}".format(index), "Each description needs text and a valid description type.")
    for index, item in enumerate(data["keywords"]):
        if not item["value"] or item["scheme"] not in ("", "Other", "GND"):
            _error(errors, "keywords.{}".format(index), "Each keyword needs text and a valid keyword scheme.")
    for index, item in enumerate(data["alternate_identifiers"]):
        if not item["value"] or not item["type"]:
            _error(errors, "alternate_identifiers.{}".format(index), "Each alternate identifier needs a value and type.")
    for index, creator in enumerate(data["creators"]):
        if not _person_name(creator):
            _error(errors, "creators.{}.name".format(index), "Please provide the creator name.")
        _validate_person_identifiers(errors, warnings, creator, "creators.{}".format(index))
    for index, contributor in enumerate(data["contributors"]):
        if not _person_name(contributor):
            _error(errors, "contributors.{}.name".format(index), "Please provide the contributor name.")
        if contributor.get("type") not in CONTRIBUTOR_TYPES:
            _error(errors, "contributors.{}.type".format(index), "Please select a valid contributor role.")
        _validate_person_identifiers(errors, warnings, contributor, "contributors.{}".format(index))
    for index, item in enumerate(data["related_identifiers"]):
        if not isinstance(item, dict) or not _text(item.get("value")):
            _error(errors, "related_identifiers.{}.value".format(index), "Please provide the related identifier.")
            continue
        if item.get("identifier_type") not in RELATED_IDENTIFIER_TYPES:
            _error(errors, "related_identifiers.{}.identifier_type".format(index), "Please select a valid identifier type.")
        if item.get("relation_type") not in RELATION_TYPES:
            _error(errors, "related_identifiers.{}.relation_type".format(index), "Please select a valid relation type.")
        if item.get("identifier_type") == "DOI" and not re.match(r"^(https?://(dx\.)?doi\.org/)?10\.\d{4,9}/\S+$", _text(item.get("value")), re.I):
            _error(errors, "related_identifiers.{}.value".format(index), "Please provide a valid DOI.")
        if item.get("identifier_type") == "URL" and not re.match(r"^https?://\S+$", _text(item.get("value")), re.I):
            _error(errors, "related_identifiers.{}.value".format(index), "Please provide a valid HTTP(S) URL.")
    for index, item in enumerate(data["data_sources"]):
        if not isinstance(item, dict) or item.get("type") not in DATA_SOURCE_TYPES or not _text(item.get("value")):
            _error(errors, "data_sources.{}".format(index), "Each data source needs a valid type and description.")
    for index, item in enumerate(data["funding_references"]):
        if not isinstance(item, dict) or not _text(item.get("funder_name")):
            _error(errors, "funding_references.{}.funder_name".format(index), "Please provide the funder name.")
        if _text(item.get("funder_identifier")) and item.get("funder_identifier_type") not in FUNDER_IDENTIFIER_TYPES:
            _error(errors, "funding_references.{}.funder_identifier_type".format(index), "Please select a valid funder identifier type.")
        if item.get("funder_identifier_type") == "ROR" and item.get("funder_identifier") and not re.match(r"^(https://ror\.org/)?0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$", item["funder_identifier"], re.I):
            _error(errors, "funding_references.{}.funder_identifier".format(index), "Please provide a valid funder ROR identifier.")
    for index, item in enumerate(data["software"]):
        if not isinstance(item, dict) or item.get("type") not in SOFTWARE_TYPES or not _text(item.get("name")) or not _text(item.get("version")):
            _error(errors, "software.{}".format(index), "Software requires a purpose, name, and version.")
    for index, item in enumerate(data["geo_locations"]):
        if not isinstance(item, dict):
            _error(errors, "geo_locations.{}".format(index), "Invalid geographic entry.")
            continue
        _coordinate(errors, item.get("latitude"), -90, 90, "geo_locations.{}.latitude".format(index))
        _coordinate(errors, item.get("longitude"), -180, 180, "geo_locations.{}.longitude".format(index))
        if bool(item.get("latitude")) != bool(item.get("longitude")):
            _error(errors, "geo_locations.{}".format(index), "Latitude and longitude must be supplied together.")
        if not any(item.values()):
            _error(errors, "geo_locations.{}".format(index), "Please complete or remove the empty geographic entry.")
        if item.get("country") and item["country"] not in COUNTRIES:
            _error(errors, "geo_locations.{}.country".format(index), "Please select a valid RADAR country.")
    for index, item in enumerate(data["related_information"]):
        if not item["value"]:
            _error(errors, "related_information.{}.value".format(index), "Please provide the related information text.")
    return {"success": not errors, "metadata": data, "errors": errors, "warnings": warnings}


def _structured_list(dataset, key):
    value = dataset.get(key)
    if value is None:
        for extra in dataset.get("extras") or []:
            if isinstance(extra, dict) and extra.get("key") == key:
                value = extra.get("value")
                break
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, dict):
        value = [value]
    return value if isinstance(value, list) else []


def _normalize_person(item):
    given = _text(item.get("given_name") or item.get("givenName"))
    family = _text(item.get("family_name") or item.get("familyName"))
    return {
        "name": _text(item.get("name") or item.get("creator_name") or item.get("creatorName")) or _person_name({"given_name": given, "family_name": family}),
        "given_name": given, "family_name": family,
        "orcid": _text(item.get("orcid") or item.get("name_identifier")),
        "affiliation": _text(item.get("affiliation")),
        "affiliation_ror": _text(item.get("affiliation_ror") or item.get("ror")),
    }


def _normalize_contributor(item):
    result = _normalize_person(item)
    result["type"] = _text(item.get("type") or item.get("contributor_type"))
    return result


def _normalize_subject_area(item):
    if isinstance(item, dict):
        return {"controlled": _text(item.get("controlled") or item.get("value")), "additional": _text(item.get("additional"))}
    return {"controlled": _text(item), "additional": ""}


def _normalize_object(item, fields):
    return {field: _text(item.get(field)) for field in fields}


def _person_name(person):
    name = _text(person.get("name"))
    if name:
        return name
    given = _text(person.get("given_name"))
    family = _text(person.get("family_name"))
    return ", ".join(part for part in (family, given) if part)


def _validate_person_identifiers(errors, warnings, person, path):
    orcid = _text(person.get("orcid"))
    if orcid and not _valid_orcid(orcid):
        _error(errors, path + ".orcid", "Please provide a valid ORCID, including its checksum.")
    elif not orcid:
        warnings.append({"field": path + ".orcid", "message": "Adding an ORCID is recommended when available."})
    ror = _text(person.get("affiliation_ror"))
    if ror and not re.match(r"^(https://ror\.org/)?0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$", ror, re.I):
        _error(errors, path + ".affiliation_ror", "Please provide a valid ROR identifier.")
    if ror and not _text(person.get("affiliation")):
        _error(errors, path + ".affiliation", "An affiliation name is required when a ROR is supplied.")


def _valid_orcid(value):
    compact = re.sub(r"^(https?://orcid\.org/)", "", value.strip(), flags=re.I).replace("-", "").upper()
    if not re.match(r"^\d{15}[\dX]$", compact):
        return False
    total = 0
    for character in compact[:15]:
        total = (total + int(character)) * 2
    remainder = (12 - (total % 11)) % 11
    return compact[-1] == ("X" if remainder == 10 else str(remainder))


def _coordinate(errors, value, minimum, maximum, field):
    if value in (None, ""):
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        _error(errors, field, "Please provide a numeric coordinate.")
        return
    if number < minimum or number > maximum:
        _error(errors, field, "Coordinate must be between {} and {}.".format(minimum, maximum))


def _normalize_language(value):
    aliases = {"de": "deu", "de-de": "deu", "german": "deu", "en": "eng", "en-us": "eng", "en-gb": "eng", "english": "eng"}
    value = _text(value).lower()
    return aliases.get(value, value if value in dict(LANGUAGES) else "")


def _required(errors, field, value, message):
    if not value:
        _error(errors, field, message)


def _error(errors, field, message):
    errors.append({"field": field, "message": message})


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()
