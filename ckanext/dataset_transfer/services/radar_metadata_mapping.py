# encoding: utf-8

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from ckanext.dataset_transfer.services.radar_reference_mapping import normalize_doi


SUBJECT_AREAS = (
    "Engineering", "Agriculture", "Architecture", "Arts and Media", "Astrophysics and Astronomy",
    "Biochemistry", "Biology", "Behavioural Sciences", "Chemistry", "Computer Science",
    "Economics", "Environmental Science and Ecology", "Ethnology",
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
CREATOR_TYPES = ("person", "institution")
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
NAME_IDENTIFIER_SCHEMES = ("Other", "ORCID", "ROR")
PROJECT_FUNDING_DEFAULTS = {
    "SFB1153": "Process chain for the production of hybrid high-performance components through tailored forming",
    "SFB1368": "oxygen-free production",
    "TRR375": "Multifunctional High-Performance Components made of hybrid porous materials",
}
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
    "creator_types": CREATOR_TYPES,
    "additional_title_types": ADDITIONAL_TITLE_TYPES,
    "description_types": DESCRIPTION_TYPES,
    "related_identifier_types": RELATED_IDENTIFIER_TYPES,
    "relation_types": RELATION_TYPES,
    "data_source_types": DATA_SOURCE_TYPES,
    "software_types": SOFTWARE_TYPES,
    "funder_identifier_types": FUNDER_IDENTIFIER_TYPES,
    "name_identifier_schemes": NAME_IDENTIFIER_SCHEMES,
    "languages": LANGUAGES,
}

LIST_FIELDS = {
    "creators", "contributors", "additional_titles", "descriptions", "keywords",
    "publishers", "subject_areas", "rights_holders", "alternate_identifiers",
    "related_identifiers", "data_sources", "software",
    "data_processing", "related_information", "funding_references",
}
SCALAR_FIELDS = {"title", "production_year", "publication_year", "language", "resource_type", "resource", "rights", "additional_rights", "version"}
ALLOWED_FIELDS = LIST_FIELDS | SCALAR_FIELDS


def map_ckan_to_radar(dataset, configured_publisher=None, project_id=None,
                      dfg_award_number=None, reference_related_identifiers=None):
    source = copy.deepcopy(dataset or {})
    organization = source.get("organization") if isinstance(source.get("organization"), dict) else {}
    organization_title = _text(organization.get("title"))
    publishers = _structured_list(source, "publishers") or _structured_list(source, "publisher")
    if publishers:
        publishers = [_normalize_publisher(item) for item in publishers]
    else:
        publisher_name = _text(configured_publisher) or organization_title
        publishers = [_normalize_publisher(publisher_name)] if publisher_name else []
    creators = _structured_list(source, "creators")
    if creators:
        creators = [_normalize_person(item) for item in creators if isinstance(item, dict)]
    elif _text(source.get("author")):
        author = _text(source.get("author"))
        # A native CKAN author string identifies a person. Keep the complete
        # value intact; do not guess where the given/family-name boundary lies.
        creators = [{
            "creator_type": "person", "name": author,
            "given_name": author, "family_name": "", "orcid": "",
            "affiliation": "", "affiliation_ror": "",
        }]

    contributors = _structured_list(source, "contributors")
    contributors = [
        _normalize_contributor(item, default_type="DataManager")
        for item in contributors if isinstance(item, dict)
    ]
    if not contributors and _text(source.get("maintainer")):
        contributors.append({
            "name": _text(source.get("maintainer")), "given_name": "", "family_name": "",
            "orcid": "", "affiliation": "", "affiliation_ror": "", "type": "DataManager",
        })
    subject_areas = _structured_list(source, "subject_area") or _structured_list(source, "subject_areas")
    subject_areas = [_text(item.get("value") if isinstance(item, dict) else item) for item in subject_areas]
    subject_areas = [value for value in subject_areas if value in SUBJECT_AREAS]
    # Use the exact RADAR vocabulary value as the initial primary subject area.
    # Researchers can remove, reorder, or supplement it in the review form.
    subject_areas = ["Engineering"] + [
        value for value in subject_areas if value != "Engineering"
    ]
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

    # CKAN creation time is only a review-form suggestion; an explicit research
    # production year always wins and the submitted review value remains editable.
    explicit_production_year = _text(_structured_value(source, "production_year"))
    production_year = explicit_production_year or _metadata_created_year(
        source.get("metadata_created")
    )
    funding_references = (
        _structured_list(source, "funding_references")
        or _structured_list(source, "fundingReference")
        or _structured_list(source, "fundingReferences")
        or _structured_list(source, "funding")
    )
    funding_references = [
        _normalize_funding(item) for item in funding_references if isinstance(item, dict)
    ]
    if not funding_references:
        default_funding = project_funding_default(project_id, dfg_award_number)
        if default_funding:
            funding_references = [default_funding]

    rights_holders = (
        _structured_list(source, "rights_holders")
        or _structured_list(source, "rightsHolder")
        or _structured_list(source, "rightsHolders")
    )
    rights_holders = [_normalize_rights_holder(item) for item in rights_holders]
    if not rights_holders and organization_title:
        rights_holders = [_organization_rights_holder(organization)]

    related_identifiers = [
        _normalize_related_identifier(item)
        for item in _structured_list(source, "related_identifiers")
        if isinstance(item, dict)
    ]
    related_identifiers = _merge_related_identifiers(
        related_identifiers,
        reference_related_identifiers or [],
    )

    return {
        "title": _text(source.get("title") or source.get("name")),
        "descriptions": descriptions,
        "creators": creators,
        "contributors": contributors,
        "publishers": publishers,
        "production_year": production_year,
        "publication_year": "",
        "subject_areas": subject_areas,
        "resource_type": resource_type,
        "resource": _text(source.get("resource_description") or source.get("title") or source.get("name")),
        "rights": rights,
        "additional_rights": "",
        "rights_holders": rights_holders,
        "keywords": keywords,
        "language": _normalize_language(source.get("language")) or "eng",
        "version": _text(source.get("version")),
        "additional_titles": [], "alternate_identifiers": [], "related_identifiers": related_identifiers,
        "data_sources": [], "software": [], "data_processing": data_processing,
        "related_information": [], "funding_references": funding_references,
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
    normalized["contributors"] = [_normalize_contributor(item, default_type="DataManager") for item in normalized["contributors"] if isinstance(item, dict)]
    # Accept legacy string publishers while normalizing new identifier metadata.
    normalized["publishers"] = [_normalize_publisher(item) for item in normalized["publishers"]]
    for key in ("data_processing",):
        normalized[key] = [_text(item.get("value") if isinstance(item, dict) else item) for item in normalized[key]]
        normalized[key] = [item for item in normalized[key] if item]
    # Accept legacy plain-text rights holders while supporting RADAR v9.3
    # organization/person identifier attributes.
    normalized["rights_holders"] = [
        _normalize_rights_holder(item) for item in normalized["rights_holders"]
    ]
    normalized["subject_areas"] = [_normalize_subject_area(item) for item in normalized["subject_areas"]]
    normalized["additional_titles"] = [_normalize_object(item, ("value", "type")) for item in normalized["additional_titles"] if isinstance(item, dict)]
    normalized["descriptions"] = [_normalize_object(item, ("value", "type")) for item in normalized["descriptions"] if isinstance(item, dict)]
    normalized["keywords"] = [_normalize_object(item, ("value", "scheme", "scheme_uri", "value_uri", "classification_code", "ontology_uri", "ontology_id")) for item in normalized["keywords"] if isinstance(item, dict)]
    normalized["alternate_identifiers"] = [_normalize_object(item, ("value", "type")) for item in normalized["alternate_identifiers"] if isinstance(item, dict)]
    normalized["related_identifiers"] = [_normalize_related_identifier(item) for item in normalized["related_identifiers"] if isinstance(item, dict)]
    normalized["data_sources"] = [_normalize_object(item, ("value", "type")) for item in normalized["data_sources"] if isinstance(item, dict)]
    normalized["software"] = [_normalize_object(item, ("name", "version", "type", "alternative_name", "alternative_version")) for item in normalized["software"] if isinstance(item, dict)]
    normalized["related_information"] = [_normalize_object(item, ("value", "type")) for item in normalized["related_information"] if isinstance(item, dict)]
    normalized["funding_references"] = [_normalize_funding(item) for item in normalized["funding_references"] if isinstance(item, dict)]
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
    for index, publisher in enumerate(data["publishers"]):
        if not publisher["name"]:
            _error(errors, "publishers.{}.name".format(index), "Please provide the publisher name.")
        identifier = publisher["name_identifier"]
        scheme = publisher["name_identifier_scheme"]
        scheme_uri = publisher["scheme_uri"]
        if identifier and scheme not in NAME_IDENTIFIER_SCHEMES:
            _error(errors, "publishers.{}.name_identifier_scheme".format(index), "Please select a valid publisher identifier scheme.")
        if identifier and not scheme_uri:
            _error(errors, "publishers.{}.scheme_uri".format(index), "Please provide the publisher identifier scheme URI.")
        if scheme == "ROR" and identifier and not _valid_ror(identifier):
            _error(errors, "publishers.{}.name_identifier".format(index), "Please provide a valid publisher ROR identifier.")
        if scheme == "ROR" and identifier and scheme_uri != "https://ror.org/":
            _error(errors, "publishers.{}.scheme_uri".format(index), "ROR publishers must use https://ror.org/ as the scheme URI.")
        if scheme == "ORCID" and identifier and not _valid_orcid(identifier):
            _error(errors, "publishers.{}.name_identifier".format(index), "Please provide a valid publisher ORCID.")
        if scheme == "ORCID" and identifier and scheme_uri != "https://orcid.org/":
            _error(errors, "publishers.{}.scheme_uri".format(index), "ORCID publishers must use https://orcid.org/ as the scheme URI.")
        if not identifier and (scheme or scheme_uri):
            _error(errors, "publishers.{}.name_identifier".format(index), "Enter a publisher identifier or clear its scheme fields.")
    for index, holder in enumerate(data["rights_holders"]):
        if not holder["name"]:
            _error(errors, "rights_holders.{}.name".format(index), "Please provide the rights holder name.")
        _validate_organization_identifier(
            errors, holder, "rights_holders.{}".format(index), "rights holder"
        )
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
        if creator.get("creator_type") not in CREATOR_TYPES:
            _error(errors, "creators.{}.creator_type".format(index), "Please select whether the creator is a person or institution.")
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
        # The development placeholder must never silently become RADAR metadata.
        if item.get("award_number") == "12345":
            _error(errors, "funding_references.{}.award_number".format(index), "Replace or remove the temporary testing award number 12345 before transfer.")
    for index, item in enumerate(data["software"]):
        if not isinstance(item, dict) or item.get("type") not in SOFTWARE_TYPES or not _text(item.get("name")) or not _text(item.get("version")):
            _error(errors, "software.{}".format(index), "Software requires a purpose, name, and version.")
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


def _structured_value(dataset, key):
    if dataset.get(key) not in (None, ""):
        return dataset.get(key)
    for extra in dataset.get("extras") or []:
        if isinstance(extra, dict) and extra.get("key") == key:
            return extra.get("value")
    return None


def _normalize_person(item):
    given = _text(item.get("given_name") or item.get("givenName"))
    family = _text(item.get("family_name") or item.get("familyName"))
    return {
        "creator_type": _normalize_creator_type(
            item.get("creator_type") or item.get("creatorType")
            or item.get("person_type") or item.get("type")
        ),
        "name": _text(item.get("name") or item.get("creator_name") or item.get("creatorName")) or _person_name({"given_name": given, "family_name": family}),
        "given_name": given, "family_name": family,
        "orcid": _text(item.get("orcid") or item.get("name_identifier")),
        "affiliation": _text(item.get("affiliation")),
        "affiliation_ror": _text(item.get("affiliation_ror") or item.get("ror")),
    }


def _normalize_creator_type(value):
    normalized = re.sub(r"[^a-z]", "", _text(value).lower())
    if normalized in ("institution", "organization", "organisation", "organizational"):
        return "institution"
    return "person"


def _normalize_contributor(item, default_type=""):
    result = _normalize_person(item)
    contributor_type = _text(
        item.get("type") or item.get("contributor_type") or item.get("contributorRole")
    )
    result["type"] = (
        contributor_type
        if contributor_type in CONTRIBUTOR_TYPES
        else default_type or contributor_type
    )
    return result


def _normalize_publisher(item):
    if not isinstance(item, dict):
        return {
            "name": _text(item), "name_identifier": "",
            "name_identifier_scheme": "", "scheme_uri": "",
        }
    return {
        "name": _text(item.get("name") or item.get("publisher_name") or item.get("value")),
        "name_identifier": _text(item.get("name_identifier") or item.get("nameIdentifier") or item.get("identifier")),
        "name_identifier_scheme": _text(item.get("name_identifier_scheme") or item.get("nameIdentifierScheme") or item.get("identifier_scheme")),
        "scheme_uri": _text(item.get("scheme_uri") or item.get("schemeURI")),
    }


def _normalize_rights_holder(item):
    if not isinstance(item, dict):
        return _normalize_publisher(item)
    return {
        "name": _text(
            item.get("name")
            or item.get("rights_holder_name")
            or item.get("rightsHolderName")
            or item.get("value")
        ),
        "name_identifier": _text(
            item.get("name_identifier")
            or item.get("nameIdentifier")
            or item.get("identifier")
        ),
        "name_identifier_scheme": _text(
            item.get("name_identifier_scheme")
            or item.get("nameIdentifierScheme")
            or item.get("identifier_scheme")
        ),
        "scheme_uri": _text(item.get("scheme_uri") or item.get("schemeURI")),
    }


def _normalize_related_identifier(item):
    identifier_type = _text(
        item.get("identifier_type") or item.get("relatedIdentifierType")
    )
    value = _text(
        item.get("value") or item.get("identifier")
        or item.get("doi") or item.get("url")
    )
    if identifier_type == "DOI":
        value = normalize_doi(value) or value
    return {
        "value": value,
        "identifier_type": identifier_type,
        "relation_type": _text(item.get("relation_type") or item.get("relationType")),
    }


def _merge_related_identifiers(existing, imported):
    """Merge automatic references without losing distinct confirmed relations."""
    merged = []
    for raw_item in list(existing) + list(imported):
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_related_identifier(raw_item)
        if not item["value"]:
            continue
        key = _related_identifier_key(item)
        matches = [candidate for candidate in merged if _related_identifier_key(candidate) == key]
        if not matches:
            merged.append(item)
            continue
        relation_type = item["relation_type"]
        if relation_type and all(
            candidate["relation_type"] != relation_type for candidate in matches
        ):
            # The same identifier may legitimately describe multiple relations.
            merged.append(item)
    return merged


def _related_identifier_key(item):
    identifier_type = _text(item.get("identifier_type")).upper()
    value = _text(item.get("value"))
    if identifier_type == "DOI":
        value = normalize_doi(value) or value
    return identifier_type, value.casefold()


def _organization_rights_holder(organization):
    holder = _normalize_rights_holder({
        "name": organization.get("title"),
        "name_identifier": organization.get("name_identifier") or organization.get("nameIdentifier"),
        "name_identifier_scheme": organization.get("name_identifier_scheme") or organization.get("nameIdentifierScheme"),
        "scheme_uri": organization.get("scheme_uri") or organization.get("schemeURI"),
    })
    ror = _text(
        organization.get("ror")
        or organization.get("ror_id")
        or _extra_value(organization, "ror")
        or _extra_value(organization, "ror_id")
    )
    if ror and not holder["name_identifier"]:
        holder.update({
            "name_identifier": ror,
            "name_identifier_scheme": "ROR",
            "scheme_uri": "https://ror.org/",
        })
    return holder


def _extra_value(container, key):
    for extra in container.get("extras") or []:
        if isinstance(extra, dict) and extra.get("key") == key:
            return extra.get("value")
    return ""


def _normalize_funding(item):
    return {
        "funder_name": _text(item.get("funder_name") or item.get("funderName")),
        "funder_identifier": _text(item.get("funder_identifier") or item.get("funderIdentifier")),
        "funder_identifier_type": _text(item.get("funder_identifier_type") or item.get("funderIdentifierType")),
        "funder_scheme_uri": _text(item.get("funder_scheme_uri") or item.get("schemeURI")),
        "award_number": _text(item.get("award_number") or item.get("awardNumber")),
        "award_uri": _text(item.get("award_uri") or item.get("awardURI")),
        "award_title": _text(item.get("award_title") or item.get("awardTitle")),
    }


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


def _valid_ror(value):
    return bool(re.match(r"^(https://ror\.org/)?0[0-9a-hj-km-np-tv-z]{6}[0-9]{2}$", value, re.I))


def _validate_organization_identifier(errors, item, path, label):
    identifier = item["name_identifier"]
    scheme = item["name_identifier_scheme"]
    scheme_uri = item["scheme_uri"]
    if identifier and scheme not in NAME_IDENTIFIER_SCHEMES:
        _error(errors, path + ".name_identifier_scheme", "Please select a valid {} identifier scheme.".format(label))
    if identifier and not scheme_uri:
        _error(errors, path + ".scheme_uri", "Please provide the {} identifier scheme URI.".format(label))
    if scheme == "ROR" and identifier and not _valid_ror(identifier):
        _error(errors, path + ".name_identifier", "Please provide a valid {} ROR identifier.".format(label))
    if scheme == "ROR" and identifier and scheme_uri != "https://ror.org/":
        _error(errors, path + ".scheme_uri", "ROR identifiers must use https://ror.org/ as the scheme URI.")
    if scheme == "ORCID" and identifier and not _valid_orcid(identifier):
        _error(errors, path + ".name_identifier", "Please provide a valid {} ORCID.".format(label))
    if scheme == "ORCID" and identifier and scheme_uri != "https://orcid.org/":
        _error(errors, path + ".scheme_uri", "ORCID identifiers must use https://orcid.org/ as the scheme URI.")
    if not identifier and (scheme or scheme_uri):
        _error(errors, path + ".name_identifier", "Enter an identifier or clear its scheme fields.")


def _metadata_created_year(value):
    value = _text(value)
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    return "{:04d}".format(parsed.year)


def normalize_project_id(value):
    compact = re.sub(r"[^A-Z0-9]", "", _text(value).upper())
    if compact in ("1153", "SFB1153"):
        return "SFB1153"
    if compact in ("1368", "SFB1368"):
        return "SFB1368"
    if compact in ("375", "TRR375"):
        return "TRR375"
    return ""


def project_funding_default(project_id, award_number=None):
    normalized_id = normalize_project_id(project_id)
    title = PROJECT_FUNDING_DEFAULTS.get(normalized_id)
    if not title:
        return None
    configured_award = _text(award_number)
    return {
        "funder_name": "Deutsche Forschungsgemeinschaft (DFG)",
        "funder_identifier": "",
        "funder_identifier_type": "",
        "funder_scheme_uri": "",
        "award_number": configured_award or "12345",
        "award_uri": "",
        "award_title": title,
        "temporary_award_number": not bool(configured_award),
    }


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
