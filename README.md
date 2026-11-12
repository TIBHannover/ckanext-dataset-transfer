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

Set the destination organization and destination URLs explicitly. Dataset transfer does not infer them
from the CKAN URL, reverse-proxy path, hostname, container name, or CRC project
identifier:

    ckanext.dataset_transfer.target_organization = sfb_1153
    ckanext.dataset_transfer.target_api_url = https://data.uni-hannover.de/api/3/action/
    ckanext.dataset_transfer.target_public_url = https://data.uni-hannover.de/
    ckan.csrf_protection.ignore_extensions = false

For Docker-based deployments, CKAN maps the setting to:

    CKANEXT__DATASET_TRANSFER__TARGET_ORGANIZATION=sfb_1153
    CKANEXT__DATASET_TRANSFER__TARGET_API_URL=https://data.uni-hannover.de/api/3/action/
    CKANEXT__DATASET_TRANSFER__TARGET_PUBLIC_URL=https://data.uni-hannover.de/
    CKAN__CSRF_PROTECTION__IGNORE_EXTENSIONS=false

Use `sfb_1153` for SFB1153 and `sfb_1368` for SFB1368. For TRR375, deployment
must remain blocked until the LUH destination organization identifier has been
verified; do not copy either SFB value or guess an identifier.

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



## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
