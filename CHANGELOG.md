# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- Restored the deprecated SFB1153 and SFB1368 `ckan.root_path` organization
  fallback for deployments targeting the original LUH repository. Explicit
  `ckanext.dataset_transfer.target_organization` configuration remains
  preferred and is required for custom destinations and TRR375.

## [1.1.1] - 2026-11-24

### Security

- Connected RADAR publishing to a server-side, request-scoped technical-account
  token provider with expiration caching and one bounded refresh after HTTP 401.
- Removed RADAR response bodies and remote exception details from application
  logs and browser-visible errors.

### Fixed

- Added a validated RADAR dataset URL template and corrected the default to
  `<context>/en/dataset/{dataset_id}` for both completed and incomplete transfers.
