# CKAN 2.11 Master Conflict-Resolution Regression Report

Date: 2026-11-12  
Branch: `master` (uncommitted working tree)  
Runtime: CKAN 2.11.6 / Python 3.10, isolated Docker Compose stack  
Network safety: LUH calls mocked; unexpected external HTTP blocked

## Result

**PASS: 36 tests passed** in 40.61 seconds on the final full rerun.

Python source parsing and JavaScript syntax checks also passed. No conflict
markers or unmerged index entries remain. The original stash remains present.

## CRC profile matrix

| Profile | Test organization | Result |
| --- | --- | --- |
| SFB1153 | `sfb_1153` | PASS |
| SFB1368 | `sfb_1368` | PASS |
| TRR375 | synthetic `verified-trr375-luh-organization` | PASS in tests only |

The real TRR375 LUH organization is deliberately unresolved and must be
verified before deployment.

## Verified behavior

- CKAN 2.11 CSRF rejection and valid-token acceptance on both extension POST
  routes, with both AJAX POST call sites reading CKAN's CSRF meta fields.
- Dataset edit permission enforcement.
- Configurable organization, action API URL, and public URL independent of
  root path, proxy path, hostname, container name, and CRC identifier.
- Organization lookup, destination authentication, dataset creation,
  URL-resource creation, uploaded-resource creation, and resource patching.
- `resource_create` HTTP 403/500 failures, `resource_patch` HTTP 500 failure,
  missing uploaded files, and one failure among multiple resources.
- Incomplete resource transfers return an error and persist an incomplete
  local record; no remote rollback deletion is attempted.
- Connection failure, timeout, invalid JSON, unexpected response structures,
  and HTTP 401/403/404/500 produce sanitized errors.
- Repeated publication, retries after incomplete transfer, destination
  creation followed by local-record failure, and PostgreSQL concurrent
  publication locking.
- Existing database schema and migrations: no column or table change was
  introduced. Destination and incomplete state are encoded in the existing
  Unicode text `published_dataset_id` column; legacy unprefixed records remain
  readable and conservatively block duplicate publication.
- Configuration declaration loading for all three destination settings.

## RADAR scope

The `master` branch does not contain the RADAR service, metadata mapper,
publisher, or RADAR test. Those files are committed only on the separate
`test` branch and are not part of the stash delta. Importing the stashed
controller or template side wholesale would therefore leave `master` with
missing-module failures.

No RADAR publication test was available on `master`, so RADAR publishing is
**not tested in this merge result**. The schema-compatible target/status
decoder remains able to read RADAR-prefixed records without importing RADAR
services. A future merge of the complete committed RADAR feature should run
its mocked RADAR regression separately.

## Docker configuration

Required production variables:

```text
CKANEXT__DATASET_TRANSFER__TARGET_ORGANIZATION=<verified destination organization>
CKANEXT__DATASET_TRANSFER__TARGET_API_URL=https://data.uni-hannover.de/api/3/action/
CKANEXT__DATASET_TRANSFER__TARGET_PUBLIC_URL=https://data.uni-hannover.de/
CKAN__CSRF_PROTECTION__IGNORE_EXTENSIONS=false
```

They map to the declared CKAN settings:

```text
ckanext.dataset_transfer.target_organization
ckanext.dataset_transfer.target_api_url
ckanext.dataset_transfer.target_public_url
ckan.csrf_protection.ignore_extensions = false
```

Use `sfb_1153` for SFB1153 and `sfb_1368` for SFB1368. Do not set TRR375's
organization until its real LUH identifier is verified. The URL settings keep
the existing LUH URLs as compatibility defaults, but explicit deployment
values are recommended.

## Untested / deployment blockers

- Real LUH and RADAR services and credentials were intentionally not used.
- Browser-driven testing was not run; CSRF was verified at rendered-page,
  protected-route, and JavaScript-source level.
- The real TRR375 LUH organization identifier remains unverified.
- Existing CRC deployment images must be rebuilt from the reviewed result and
  their installed revision verified before release.

## Recommendation

The conflict-resolved LUH/CKAN 2.11 implementation is suitable for controlled
staging review. Production release remains blocked on the verified TRR375
organization, deployment image rebuild/verification, and any separately
required complete RADAR feature merge and regression.
