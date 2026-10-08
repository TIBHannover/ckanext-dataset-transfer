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
    ckanext.dataset_transfer.radar.default_subject_area = Other
    ckanext.dataset_transfer.radar.default_rights = Other
    ckanext.dataset_transfer.radar.metadata_identifier_prefix = 10.0000

For local testing, either provide a temporary RADAR access token:

    ckanext.dataset_transfer.radar.access_token = YOUR_ACCESS_TOKEN

Or provide the OAuth credentials so the extension can request a token:

    ckanext.dataset_transfer.radar.client_id = tib
    ckanext.dataset_transfer.radar.client_secret = YOUR_CLIENT_SECRET
    ckanext.dataset_transfer.radar.redirect_url = https://www.tib.eu
    ckanext.dataset_transfer.radar.user_name = YOUR_RADAR_USERNAME
    ckanext.dataset_transfer.radar.user_password = YOUR_RADAR_PASSWORD

The generated descriptive metadata XML is validated locally against the bundled
RADAR v9.3 descriptive schema, uploaded to RADAR, and then checked with RADAR's
`/metadata/validate` endpoint. To override the bundled schema path, set:

    ckanext.dataset_transfer.radar.descriptive_xsd_path = /path/to/RadarDataset.xsd

When overriding the schema path, keep the RADAR v9.3 `RadarDataset.xsd`,
`RadarElements.xsd`, and `RadarTypes.xsd` files in the same directory because
the dataset schema imports the other two schemas.


## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
