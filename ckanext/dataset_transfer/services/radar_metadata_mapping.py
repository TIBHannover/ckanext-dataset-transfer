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
FIXED_RESOURCE_TYPE = "Dataset"
FIXED_SUBJECT_AREA = "Engineering"
DFG_FUNDER_NAME = "Deutsche Forschungsgemeinschaft (DFG)"
DFG_ROR = "https://ror.org/018mejw64"
DFG_ROR_SCHEME_URI = "https://ror.org/"
NAME_PARTICLES = {
    "da", "de", "del", "della", "der", "di", "du", "la", "le", "ten",
    "ter", "van", "von", "zu", "zum", "zur",
}
ACADEMIC_TITLES = {
    "dr", "dr.", "prof", "prof.", "professor", "phd", "ph.d.",
}
ORGANIZATION_WORDS = {
    "academy", "department", "faculty", "gmbh", "group", "institute",
    "institut", "laboratory", "labor", "university", "universität",
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
                      dfg_award_number=None, reference_descriptions=None):
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
        creators = parse_ckan_authors(source.get("author"))

    contributors = _structured_list(source, "contributors")
    contributors = [
        _normalize_contributor(item, default_type="DataManager")
        for item in contributors if isinstance(item, dict)
    ]
    if not contributors and _text(source.get("maintainer")):
        contributors = []
        for maintainer in parse_person_names(source.get("maintainer")):
            maintainer["type"] = "DataManager"
            contributors.append(
                _normalize_contributor(maintainer, default_type="DataManager")
            )
    subject_areas = _structured_list(source, "subject_area") or _structured_list(source, "subject_areas")
    subject_areas = [_text(item.get("value") if isinstance(item, dict) else item) for item in subject_areas]
    subject_areas = [value for value in subject_areas if value in SUBJECT_AREAS]
    # Use the exact RADAR vocabulary value as the initial primary subject area.
    # Researchers can remove, reorder, or supplement it in the review form.
    subject_areas = [FIXED_SUBJECT_AREA] + [
        value for value in subject_areas if value != FIXED_SUBJECT_AREA
    ]
    resource_type = FIXED_RESOURCE_TYPE
    rights = mapped_ckan_rights(source)
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
    descriptions = _merge_descriptions(descriptions, reference_descriptions or [])

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
    funding_references = _merge_funding_references(
        project_funding_default(project_id, dfg_award_number),
        funding_references,
    )

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


def parse_person_names(value):
    """Parse a legacy CKAN person-list value into reviewable RADAR people.

    Strong separators are handled before comma conventions. Ambiguous comma
    orientation is retained in ``name`` and marked for explicit review instead
    of being silently treated as certain.
    """
    original = value if isinstance(value, str) else ""
    normalized = _text(original)
    if not normalized:
        return []

    people = []
    strong_segments = (
        [part.strip() for part in normalized.split(";") if part.strip()]
        if ";" in normalized
        else [normalized]
    )
    for segment in strong_segments:
        entries, split_is_ambiguous = _split_author_entries(segment)
        for entry in entries:
            person = _parse_author_entry(entry)
            person["source_name"] = original
            person["needs_review"] = bool(
                person["needs_review"] or split_is_ambiguous
            )
            people.append(person)
    return people


def parse_ckan_authors(author_string):
    """Backward-compatible name for the shared legacy person-name parser."""
    people = parse_person_names(author_string)
    for person in people:
        person["source_author"] = person["source_name"]
    return people


def _split_author_entries(author):
    possible_conjunction_parts = [
        part.strip()
        for part in re.split(r"\s+and\s+", author, flags=re.I)
        if part.strip()
    ]
    author_words = {
        word.casefold().strip(".,") for word in author.split()
    }
    if (
        len(possible_conjunction_parts) > 1
        and not author_words & ORGANIZATION_WORDS
        and all(
            _looks_like_author_segment(part)
            for part in possible_conjunction_parts
        )
    ):
        conjunction_parts = possible_conjunction_parts
    else:
        conjunction_parts = [author]
    entries = []
    ambiguous = False
    for part in conjunction_parts:
        comma_parts = [item.strip() for item in part.split(",") if item.strip()]
        if len(comma_parts) <= 1:
            entries.extend(comma_parts)
        elif _is_repeated_family_initial_list(comma_parts):
            entries.extend(
                "{}, {}".format(comma_parts[index], comma_parts[index + 1])
                for index in range(0, len(comma_parts), 2)
            )
        elif all(_looks_like_full_name(item) for item in comma_parts):
            entries.extend(comma_parts)
        elif len(comma_parts) == 2:
            # A single comma commonly belongs to one name (Family, Given or
            # Given, Family). Keep it together; orientation is handled below.
            entries.append(part.strip())
        else:
            # The number of people cannot be established safely. Preserve the
            # complete segment as one review-required creator.
            entries.append(part.strip())
            ambiguous = True
    return entries, ambiguous


def _looks_like_author_segment(value):
    comma_parts = [part.strip() for part in value.split(",") if part.strip()]
    if not comma_parts:
        return False
    if len(comma_parts) == 1:
        return _looks_like_full_name(comma_parts[0])
    return (
        _is_repeated_family_initial_list(comma_parts)
        or all(_looks_like_full_name(part) for part in comma_parts)
        or len(comma_parts) == 2
    )


def _is_repeated_family_initial_list(parts):
    return (
        len(parts) >= 4
        and len(parts) % 2 == 0
        and all(
            _looks_like_family(parts[index]) and _is_initials(parts[index + 1])
            for index in range(0, len(parts), 2)
        )
    )


def _parse_author_entry(entry):
    name = re.sub(r"\s+", " ", entry).strip()
    given = ""
    family = ""
    needs_review = False
    comma_parts = [part.strip() for part in name.split(",")]

    if len(comma_parts) == 2 and all(comma_parts):
        left, right = comma_parts
        if _is_initials(right):
            family, given = left, right
        elif _is_all_upper_name(left) and not _is_all_upper_name(right):
            family, given = left, right
            # Case is useful evidence, but never sufficient for silent certainty.
            needs_review = True
        else:
            given, family = left, right
            needs_review = True
    elif len(comma_parts) > 1:
        needs_review = True
    else:
        words = name.split()
        lowered = {word.casefold().strip(".,") for word in words}
        if len(words) == 1 or lowered & ORGANIZATION_WORDS:
            needs_review = True
        elif words[0].casefold() in ACADEMIC_TITLES:
            needs_review = True
        else:
            family_start = len(words) - 1
            while (
                family_start > 0
                and words[family_start - 1].casefold().strip(".,") in NAME_PARTICLES
            ):
                family_start -= 1
            given = " ".join(words[:family_start])
            family = " ".join(words[family_start:])
            if not given or not family:
                given = ""
                family = ""
                needs_review = True

    return {
        "creator_type": "person",
        "name": name,
        "given_name": given,
        "family_name": family,
        "orcid": "",
        "affiliation": "",
        "affiliation_ror": "",
        "needs_review": needs_review,
    }


def _looks_like_full_name(value):
    words = value.split()
    return len(words) >= 2 and not _is_initials(value)


def _looks_like_family(value):
    return bool(value and not any(character.isdigit() for character in value))


def _is_initials(value):
    tokens = value.replace("-", " ").split()
    return bool(tokens) and all(re.match(r"^[^\W\d_]\.?$", token, re.UNICODE) for token in tokens)


def _is_all_upper_name(value):
    letters = [character for character in value if character.isalpha()]
    return bool(letters) and all(character.isupper() for character in letters)


def apply_fixed_radar_metadata(metadata, dataset, project_id=None,
                               dfg_award_number=None,
                               reference_descriptions=None):
    """Reapply server-controlled RADAR values to reviewed browser metadata."""
    data = normalize_reviewed_metadata(metadata)
    data["resource_type"] = FIXED_RESOURCE_TYPE
    data["rights"] = mapped_ckan_rights(dataset)
    data["additional_rights"] = ""

    additional_subjects = []
    seen_subjects = {(FIXED_SUBJECT_AREA.casefold(), "")}
    for area in data["subject_areas"]:
        normalized_area = _normalize_subject_area(area)
        controlled = normalized_area["controlled"]
        key = (controlled.casefold(), normalized_area["additional"].casefold())
        if controlled == FIXED_SUBJECT_AREA or key in seen_subjects:
            continue
        seen_subjects.add(key)
        additional_subjects.append(normalized_area)
    data["subject_areas"] = [
        {"controlled": FIXED_SUBJECT_AREA, "additional": ""}
    ] + additional_subjects

    data["funding_references"] = _merge_funding_references(
        project_funding_default(project_id, dfg_award_number),
        data["funding_references"],
    )
    data["descriptions"] = _merge_descriptions(
        data["descriptions"], reference_descriptions or []
    )
    return data


def fixed_radar_metadata_errors(dataset, project_id=None,
                                dfg_award_number=None):
    """Return configuration/source errors for fields fixed by server policy."""
    errors = []
    license_id = _text((dataset or {}).get("license_id"))
    if not mapped_ckan_rights(dataset):
        message = (
            "The CKAN dataset licence is not specified. Update the licence in "
            "CKAN before transferring to RADAR."
            if license_id.lower() == "notspecified" or not license_id
            else "The CKAN dataset licence is not supported by RADAR. Update the licence in CKAN before transferring."
        )
        _error(errors, "rights", message)

    normalized_project = normalize_project_id(project_id)
    if not normalized_project:
        _error(
            errors,
            "funding_references",
            "Configure CKANEXT__CRC__PROJECT__ID with SFB1153, SFB1368, or TRR375 before transferring to RADAR.",
        )
    award_number = _text(dfg_award_number)
    if not award_number or award_number == "12345":
        _error(
            errors,
            "funding_references",
            "Configure a verified DFG project number in CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER before transferring to RADAR.",
        )
    return errors


def mapped_ckan_rights(dataset):
    return LICENSE_MAP.get(_text((dataset or {}).get("license_id")).lower(), "")


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
    if data["resource_type"] != FIXED_RESOURCE_TYPE:
        _error(errors, "resource_type", "RADAR resource type must be Dataset.")
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
    if not any(
        area.get("controlled") == FIXED_SUBJECT_AREA
        for area in data["subject_areas"] if isinstance(area, dict)
    ):
        _error(errors, "subject_areas", "Engineering is required as the primary RADAR subject area.")
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
        if creator.get("needs_review"):
            _error(
                errors,
                "creators.{}.needs_review".format(index),
                "Please verify the automatically extracted given and family names.",
            )
        _validate_person_identifiers(errors, warnings, creator, "creators.{}".format(index))
    for index, contributor in enumerate(data["contributors"]):
        if contributor.get("creator_type") not in CREATOR_TYPES:
            _error(errors, "contributors.{}.creator_type".format(index), "Please select whether the contributor is a person or institution.")
        if not _person_name(contributor):
            _error(errors, "contributors.{}.name".format(index), "Please provide the contributor name.")
        if contributor.get("type") not in CONTRIBUTOR_TYPES:
            _error(errors, "contributors.{}.type".format(index), "Please select a valid contributor role.")
        if contributor.get("needs_review"):
            _error(
                errors,
                "contributors.{}.needs_review".format(index),
                "Please verify the automatically extracted given and family names.",
            )
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
        if item.get("funder_identifier_type") == "ROR" and item.get("funder_identifier") and item.get("funder_scheme_uri") != DFG_ROR_SCHEME_URI:
            _error(errors, "funding_references.{}.funder_scheme_uri".format(index), "ROR funders must use https://ror.org/ as the scheme URI.")
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
        "source_name": _text(item.get("source_name") or item.get("source_author")),
        "needs_review": _boolean(item.get("needs_review")),
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
    normalized = {
        "funder_name": _text(item.get("funder_name") or item.get("funderName")),
        "funder_identifier": _text(item.get("funder_identifier") or item.get("funderIdentifier")),
        "funder_identifier_type": _text(item.get("funder_identifier_type") or item.get("funderIdentifierType")),
        "funder_scheme_uri": _text(item.get("funder_scheme_uri") or item.get("schemeURI")),
        "award_number": _text(item.get("award_number") or item.get("awardNumber")),
        "award_uri": _text(item.get("award_uri") or item.get("awardURI")),
        "award_title": _text(item.get("award_title") or item.get("awardTitle")),
    }
    if item.get("fixed"):
        normalized["fixed"] = True
    if item.get("project_id"):
        normalized["project_id"] = _text(item.get("project_id"))
    return normalized


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
        "funder_name": DFG_FUNDER_NAME,
        "funder_identifier": DFG_ROR,
        "funder_identifier_type": "ROR",
        "funder_scheme_uri": DFG_ROR_SCHEME_URI,
        "award_number": configured_award,
        "award_uri": "",
        "award_title": title,
        "project_id": normalized_id,
        "fixed": True,
    }


def _merge_funding_references(primary, additional):
    merged = [primary] if primary else []
    for raw_item in additional or []:
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_funding(raw_item)
        if not item["funder_name"]:
            continue
        if primary and _same_funding_reference(primary, item):
            continue
        merged.append(item)
    return merged


def _same_funding_reference(left, right):
    left_award = _text(left.get("award_number")).casefold()
    right_award = _text(right.get("award_number")).casefold()
    if left_award and right_award and left_award == right_award:
        return True
    left_title = _text(left.get("award_title")).casefold()
    right_title = _text(right.get("award_title")).casefold()
    return bool(left_title and right_title and left_title == right_title)


def _merge_descriptions(existing, imported):
    merged = []
    seen = set()
    for raw_item in list(existing or []) + list(imported or []):
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_object(raw_item, ("value", "type"))
        if not item["value"]:
            continue
        key = (item["type"].casefold(), " ".join(item["value"].split()).casefold())
        if key in seen:
            continue
        seen.add(key)
        if raw_item.get("fixed"):
            item["fixed"] = True
        if raw_item.get("source"):
            item["source"] = _text(raw_item.get("source"))
        merged.append(item)
    return merged


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


def _boolean(value):
    if isinstance(value, bool):
        return value
    return _text(value).lower() in ("1", "true", "yes", "on")
