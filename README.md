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
