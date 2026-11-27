# ckanext-dataset-transfer

Publish a dataset to another CKAN instance.


## Requirements


Compatibility with core CKAN versions:

| CKAN version    | Compatible?   |
| --------------- | ------------- |
| 2.8 and earlier | not tested    |
| 2.9             | not tested in current branch |
| 2.10            | Yes, tested in Docker with Python 3.10 |
| 2.11            | Yes, tested in Docker with Python 3.10 |


## Installation


To install ckanext-dataset-transfer:

1. Activate your CKAN virtual environment, for example:

        . /usr/lib/ckan/default/bin/activate

2. Clone the source and install it on the virtualenv

        git clone https://github.com/TIBHannover/ckanext-dataset-transfer.git
        cd ckanext-dataset-transfer
        pip install -e .
        pip install -r requirements.txt

3. Add `dataset_transfer` to the `ckan.plugins` setting in your CKAN
   config file (by default the config file is located at
   `/etc/ckan/default/ckan.ini`).

4. migrate the db

        ckan -c /path/to/ckan.ini db upgrade -p dataset_transfer

4. Restart CKAN. For example if you've deployed CKAN with Apache on Ubuntu:

        sudo service nginx reload

## LUH Destination Configuration

Set the destination organization and destination URLs explicitly. The
organization setting is required for reliable deployments:

    ckanext.dataset_transfer.target_organization = sfb_1153
    ckanext.dataset_transfer.target_api_url = https://data.uni-hannover.de/api/3/action/
    ckanext.dataset_transfer.target_public_url = https://data.uni-hannover.de/
    ckan.csrf_protection.ignore_extensions = false

For Docker-based deployments, CKAN maps the setting to:

    CKANEXT__DATASET_TRANSFER__TARGET_ORGANIZATION=sfb_1153
    CKANEXT__DATASET_TRANSFER__TARGET_API_URL=https://data.uni-hannover.de/api/3/action/
    CKANEXT__DATASET_TRANSFER__TARGET_PUBLIC_URL=https://data.uni-hannover.de/
    CKAN__CSRF_PROTECTION__IGNORE_EXTENSIONS=false

For SFB1368, use the same URL settings with:

    ckanext.dataset_transfer.target_organization = sfb_1368

or, in Docker:

    CKANEXT__DATASET_TRANSFER__TARGET_ORGANIZATION=sfb_1368

Use `sfb_1153` for SFB1153 and `sfb_1368` for SFB1368. For TRR375, configure
only a verified destination organization identifier; do not copy either SFB
value or guess an identifier.

For temporary backward compatibility, an installation without
`target_organization` still maps a `ckan.root_path` containing `sfb1153/ckan`
or `sfb1368/ckan` to the corresponding organization, but only when both
destination URLs resolve to the original LUH repository shown above. This
fallback is deprecated, logs a warning, and will not run for custom
destinations or TRR375. Configure `target_organization` explicitly before the
fallback is removed.

CKAN's Docker entrypoint translates double underscores in `CKANEXT__...`
variables into dots, so the variables above map to the three declared
`ckanext.dataset_transfer.*` settings. Existing LUH URLs remain the code
defaults for backward compatibility, but production deployments should set
them explicitly. The CKAN core CSRF setting removes CKAN 2.11's temporary
extension exemption: `false` disables the exemption, so CKAN protects the
extension routes. The extension's AJAX requests send CKAN's generated token.

If destination dataset creation succeeds but any resource fails, the extension
stores an incomplete transfer record and returns an error. It does not delete
the partially created destination dataset. An administrator must reconcile the
remote dataset before another publication attempt.


## RADAR Test Configuration

RADAR publishing can be tested from the same publish page by selecting
`RADAR` as the publish target.

Add the RADAR test settings to your local CKAN config:

    ckanext.dataset_transfer.radar.context_url = https://test.radar-service.eu/radar
    ckanext.dataset_transfer.radar.ingest_url = https://test.radar-service.eu/radar-ingest
    ckanext.dataset_transfer.radar.workspace_id = YOUR_WORKSPACE_ID
    ckanext.dataset_transfer.radar.responsible_email = your-email@example.org
    ckanext.dataset_transfer.radar.retention_period = 10
    ckanext.dataset_transfer.radar.schema_key = RDDM
    ckanext.dataset_transfer.radar.schema_version = 9.3
    ckanext.dataset_transfer.radar.publisher = TIB
    ckanext.dataset_transfer.radar.metadata_identifier_prefix = 10.0000
    ckanext.dataset_transfer.radar.verification_retry_interval = 5
    ckanext.dataset_transfer.radar.verification_max_duration = 120
    ckanext.dataset_transfer.radar.dataset_url_template = https://test.radar-service.eu/radar/en/dataset/{dataset_id}
    ckanext.dataset_transfer.radar.client_id = YOUR_CLIENT_ID
    ckanext.dataset_transfer.radar.client_secret = YOUR_CLIENT_SECRET
    ckanext.dataset_transfer.radar.redirect_url = https://www.tib.eu
    ckanext.dataset_transfer.radar.user_name = YOUR_TECHNICAL_ACCOUNT_USERNAME
    ckanext.dataset_transfer.radar.user_password = YOUR_TECHNICAL_ACCOUNT_PASSWORD

Project-specific DFG funding defaults use `ckanext.crc.project.id` (or the
Docker variable `CKANEXT__CRC__PROJECT__ID`). Configure the verified award
number before transfer with:

    ckanext.dataset_transfer.radar.dfg_award_number = VERIFIED_DFG_PROJECT_NUMBER

Docker deployments may use
`CKANEXT_DATASET_TRANSFER_RADAR_DFG_AWARD_NUMBER`. This must contain the
verified DFG project number for the current CRC deployment. A missing value
(or the former development placeholder `12345`) blocks RADAR transfer.

Destination-aware transfer status does not require a database migration. New
records store an explicit LUH or RADAR marker together with the remote dataset
identifier in the existing `published_dataset_id` column. Older unmarked rows
are displayed as legacy transfers with an unknown destination; their target is
not guessed from DOI prefixes or URLs.

### RADAR authentication

RADAR publication uses a shared technical account configured by an
administrator. This is server-side authentication, not user-specific OAuth:
the configured technical account may appear in RADAR as the uploading user.
The CKAN user's existing dataset-edit authorization is still checked before a
publication can be triggered, but the CKAN username is never substituted for
the configured RADAR username.

The controller injects a request-scoped token provider into `RadarPublisher`.
The provider posts the five authentication values to the configured RADAR
context URL plus `/api/tokens`, requires HTTPS, and retains the bearer token
only in memory for the current transfer. When RADAR returns an expiration
lifetime, the token is refreshed shortly before expiry. Without expiration
information it is retained only for that provider/transfer. An HTTP 401 clears
the cached token and permits one authentication retry; repeated failures stop
publication. Credentials and bearer tokens are never rendered in templates or
JavaScript, persisted in dataset metadata or new tables, or included in logs.

Docker/GitLab deployments can supply the exact variables below. Store the
secret and password as protected, masked CI/CD variables. Literal unresolved
`${...}` or `{{...}}` placeholders are rejected:

    CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_ID
    CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_SECRET
    CKANEXT_DATASET_TRANSFER_RADAR_REDIRECT_URL
    CKANEXT_DATASET_TRANSFER_RADAR_USER_NAME
    CKANEXT_DATASET_TRANSFER_RADAR_USER_PASSWORD

The context URL is also read directly from
`CKANEXT_DATASET_TRANSFER_RADAR_CONTEXT_URL` when the CKAN config key is absent.
For Docker YAML, configure the public link explicitly:

    CKANEXT_DATASET_TRANSFER_RADAR_DATASET_URL_TEMPLATE: "https://test.radar-service.eu/radar/en/dataset/{dataset_id}"

The template must contain `{dataset_id}`. Its default is derived from the
configured context URL as `<context>/en/dataset/{dataset_id}`, which supports
the standard test and production RADAR layouts. The same formatter is used for
successful and incomplete transfers; links are never guessed from DOI values.

RADAR response bodies, authorization data, and request bodies containing
authentication values are not logged. Operational logs retain the operation,
HTTP status, and dataset identifier. User-facing authentication and API errors
are deliberately sanitized.

The historical Alembic revision `8c7e4d91a2f0` remains as a no-op compatibility
marker because an installation may already be stamped at that revision. It does
not create, use, downgrade, or drop OAuth tables. The removed feature no longer
uses Redis and does not require an OAuth database migration.

Automated tests use mock token and RADAR API responses and never contact real
RADAR or LUH endpoints.

## RADAR Dataset Lifecycle Status Synchronization

A completed transfer and formal RADAR publication are separate facts. The
extension keeps the existing local transfer status (for example `transferred`,
`pending_publication`, `resource_upload_failure`, or another persisted
incomplete stage) and supplements it with the current RADAR lifecycle state.
The existence of a reserved DOI is not treated as proof of publication.

For transferred RADAR datasets, CKAN performs the documented read-only
`GET <radar-context>/api/datasets/{dataset_id}` request. The dataset identifier
is taken only from CKAN's persisted transfer record, the base URL is taken only
from `ckanext.dataset_transfer.radar.context_url`, and authentication reuses the
server-side `RadarTokenProvider` technical account. Callers supply only their
CKAN API token; RADAR credentials and bearer tokens are never returned.

The known RADAR states are displayed as `Pending`, `In Review`, `Published`,
and `Archived`. RADAR's `REVIEW` state is exposed consistently as
`IN_REVIEW`; `IN_REVIEW` is also accepted for compatibility. An unknown,
non-empty state is preserved and converted to a safe human-readable label—it
is never silently changed to `PENDING`.

The CKAN dataset page shows transfer completion separately from repository
status and retains the transfer date, DOI, RADAR identifier, and destination
link. A RADAR outage does not prevent the page from rendering. With no prior
value it shows `Temporarily unavailable`; if an older valid value exists, it is
shown explicitly as cached together with its last successful check time.

### Action API

`dataset_transfer_status` remains backward compatible: `dataset_id`, `target`,
`status`, `doi`, `published_url`, and `destination_dataset_id` are unchanged.
The following fields are additive:

- `transfer_status`: the local transfer result, independent of publication.
- `repository_status`: normalized RADAR state, or `null` when unavailable or
  for LUH.
- `repository_status_raw`: state spelling received from RADAR.
- `repository_status_label`: display-safe label.
- `repository_status_available`: whether the latest attempted check succeeded.
- `repository_status_source`: `radar_api`, `cache`, `stale_cache`, or
  `unavailable`.
- `repository_status_checked_at`: UTC time of the successful live lookup (or
  attempted lookup when no cached value exists).
- `repository_status_error`: sanitized machine-readable failure code, or
  `null`.

Request a cached-or-live result (the default):

```bash
curl -sS -X POST \
  "${CKAN_URL}/api/3/action/dataset_transfer_status" \
  -H "Authorization: ${CKAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"dataset_id\":\"${DATASET_ID}\",\"target\":\"radar\"}"
```

Force a fresh, still read-only RADAR request with the literal JSON boolean
`refresh: true`:

```bash
curl -sS -X POST \
  "${CKAN_URL}/api/3/action/dataset_transfer_status" \
  -H "Authorization: ${CKAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"dataset_id\":\"${DATASET_ID}\",\"target\":\"radar\",\"refresh\":true}" \
  | python3 -m json.tool
```

An in-review result has this shape inside CKAN's standard `result` envelope:

```json
{
  "dataset_id": "pore-web-app-test-3",
  "target": "radar",
  "status": "pending_publication",
  "transfer_status": "transferred",
  "repository_status": "IN_REVIEW",
  "repository_status_raw": "REVIEW",
  "repository_status_label": "In Review",
  "repository_status_available": true,
  "repository_status_source": "radar_api",
  "repository_status_checked_at": "2026-11-26T16:30:00Z",
  "repository_status_error": null,
  "doi": "10.80836/yxa0acjqn40v9f28",
  "published_url": "https://test.radar-service.eu/radar/en/dataset/yxa0acjqn40v9f28",
  "destination_dataset_id": "yxa0acjqn40v9f28"
}
```

`PENDING`, `PUBLISHED`, and `ARCHIVED` use the same structure with labels
`Pending`, `Published`, and `Archived`. When RADAR is unavailable and no cached
value exists, `repository_status` and `repository_status_raw` are `null`, the
label is `Temporarily unavailable`, `repository_status_available` is `false`,
the source is `unavailable`, and `repository_status_error` contains a sanitized
code such as `timeout`, `authentication_failed`, `dataset_not_found`,
`rate_limited`, `invalid_response`, or `service_unavailable`. Raw RADAR error
bodies are not exposed.

LUH requests do not contact RADAR. They retain their existing response and add
`transfer_status`; all `repository_status*` fields are `null`.

### Cache, configuration, and operation

Successful lookups are held in a bounded, process-local cache keyed by RADAR
context URL and dataset identifier. The default lifetime is 300 seconds and
the cache contains at most 512 entries per CKAN worker. `refresh: false` uses a
fresh cached entry; `refresh: true` bypasses it. A failed refresh does not
overwrite the last valid state and returns it with source `stale_cache` and
`repository_status_available: false`.

Optional settings are:

```ini
ckanext.dataset_transfer.radar.status_cache_ttl = 300
ckanext.dataset_transfer.radar.status_timeout = 10
```

The status HTTP timeout is bounded to 1–60 seconds. No database migration,
queue, Redis service, or new credential configuration is required. Restart
CKAN after installing the updated extension or changing configuration. No
frontend asset build is needed. A release deployment using an immutable CKAN
image must rebuild that image so it contains this extension version; the
existing Docker override can be used for test deployment.

For a TRR375 test-instance check:

```bash
export CKAN_URL="https://ckan.service.tib.eu/trr375-test"
read -rsp "CKAN API token: " CKAN_API_TOKEN
echo
export DATASET_ID="pore-web-app-test-3"

curl -sS -X POST \
  "${CKAN_URL}/api/3/action/dataset_transfer_status" \
  -H "Authorization: ${CKAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"dataset_id\":\"${DATASET_ID}\",\"target\":\"radar\",\"refresh\":true}" \
  | python3 -m json.tool
```

Open `${CKAN_URL}/dataset/${DATASET_ID}` and verify the same lifecycle label.
For lifecycle-transition testing, use a non-production RADAR dataset, change it
through an allowed step such as Pending to In Review, and repeat the API call
with `refresh: true`. Test outages only with mocks or controlled test
configuration. For LUH compatibility, repeat the request with `target: luh`
and a suitable LUH test dataset.

The generated descriptive metadata XML is validated locally against the bundled
RADAR v9.3 descriptive schema, uploaded to RADAR, and then checked with RADAR's
`/metadata/validate` endpoint. To override the bundled schema path, set:

    ckanext.dataset_transfer.radar.descriptive_xsd_path = /path/to/RadarDataset.xsd

When overriding the schema path, keep the RADAR v9.3 `RadarDataset.xsd`,
`RadarElements.xsd`, and `RadarTypes.xsd` files in the same directory because
the dataset schema imports the other two schemas.


## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
# External Publishing API

## Managing External Repository Credentials

The API token issued by the source CKAN instance and the LUH destination token
serve different purposes. A source CKAN token authenticates the caller to this
CKAN. The LUH token is created in an authorized account on the LUH Research Data
Repository and authorizes transfers to that separate CKAN instance.

After obtaining an LUH token from the LUH account's API-token page, sign in to
the source CKAN and open **External API Tokens** in the user-profile navigation,
or visit `/dataset_transfer/credentials`. Enter the token in the password field
and save it. Existing tokens are rendered only as twelve mask characters plus
their final four characters; the complete stored value is never returned to the
browser. The page supports replacement, removal, and a non-mutating connection
test against the configured LUH organization. Replacement takes effect for the
next transfer. Removal leaves transfer history and RADAR publication unchanged.

LUH publication from both the browser workflow and the authenticated Dataset
Transfer Action API resolves the stored credential belonging to the identified
source-CKAN user. A source CKAN API token is never forwarded to LUH as a
destination credential.

The existing `publish_api_token.api_token` column stores LUH tokens in
plaintext. This change preserves that representation so existing credentials
remain usable and requires no migration. Database access, backups, and operator
permissions must therefore be protected as credential-bearing systems. No
encryption-at-rest scheme is introduced without a stable, server-managed key
and an explicit migration/rotation design.

The extension exposes authenticated CKAN Action API operations for clients such
as PORE. Send a normal source-CKAN API token in the `Authorization` header. The
token identifies the user, but does not grant extra rights: validation and
publication require `package_update` on the source dataset. Status requires
normal `package_show` access. Browser login and cookies are not required.

Configure destinations with:

```ini
ckanext.dataset_transfer.luh.enabled = true
ckanext.dataset_transfer.radar.enabled = true
```

LUH remains enabled when its flag is omitted for compatibility. RADAR is
disabled by default and must be enabled explicitly on TRR375 (Docker:
`CKANEXT__DATASET_TRANSFER__RADAR__ENABLED: "true"`). Disabled targets are
hidden in the UI and rejected by the API. RADAR credentials remain server-side.
LUH uses the authenticated user's already stored destination token, or the
optional one-request `luh_api_token`; this token is never returned or persisted
by the Action API.

The examples use the configured TRR375 test URL. Verify this base URL against
the deployment configuration before running them:

```bash
BASE=https://ckan.service.tib.eu/trr375-test
TOKEN=YOUR_CKAN_API_TOKEN

# List destinations
curl -sS "$BASE/api/3/action/dataset_transfer_targets" \
  -H "Authorization: $TOKEN" -H 'Content-Type: application/json' -d '{}'

# Validate RADAR metadata (radar_metadata may contain reviewed metadata)
curl -sS "$BASE/api/3/action/dataset_transfer_validate" \
  -H "Authorization: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dataset_id":"test-instance-for-publish","target":"radar"}'

# CREATES a RADAR destination dataset (initial RADAR state is pending publication)
curl -sS "$BASE/api/3/action/dataset_transfer_publish" \
  -H "Authorization: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dataset_id":"test-instance-for-publish","target":"radar","terms_accepted":true,"rights_confirmed":true}'

# Check target-specific transfer status
curl -sS "$BASE/api/3/action/dataset_transfer_status" \
  -H "Authorization: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dataset_id":"test-instance-for-publish","target":"radar"}'

# CREATES an LUH destination dataset; omit luh_api_token to use the stored token
curl -sS "$BASE/api/3/action/dataset_transfer_publish" \
  -H "Authorization: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dataset_id":"test-instance-for-publish","target":"luh","terms_accepted":true,"rights_confirmed":true,"luh_api_token":"YOUR_LUH_API_TOKEN"}'
```

`dataset_transfer_validate` returns `valid`, normalized `metadata`, `errors`,
and `warnings` without changing either repository. `dataset_transfer_publish`
also accepts `radar_metadata`. Consent fields must be literal JSON booleans and
both must be `true`. Successful LUH responses report `transferred`; successful
RADAR transfer responses report `pending_publication`, because transfer into
RADAR is not proof of public release. `dataset_transfer_status` returns
`not_transferred`, `transferred`, `pending_publication`, or the exact persisted
incomplete-transfer stage.

CKAN returns its standard Action API envelope (`success` and `result` or
`error`). Expected failures include authentication/authorization errors,
disabled or invalid targets, structured RADAR metadata errors, missing server
configuration, missing/invalid LUH credentials, conflicts, sanitized remote
errors, and persisted incomplete-transfer details. Reconcile incomplete or
ambiguous destination creation before retrying; the service deliberately does
not retry creation after timeouts.

Publication remains synchronous. Large RADAR archives can exceed proxy or
client timeouts even though transfer continues in the request worker. A future
asynchronous version should use a durable external job queue, persisted job
IDs, and idempotent reconciliation—not an in-process thread.

No new migration is required. A rebuilt Docker-CKAN image containing this
extension is required. After restart, verify registration with
`/api/3/action/status_show` and an authenticated call to
`dataset_transfer_targets`; verify the installed source/version inside the
container with `pip show ckanext-dataset-transfer` and inspect the loaded
`ckanext.dataset_transfer.actions` module path. Existing CKAN test overrides can
be used with the two enable flags above.
