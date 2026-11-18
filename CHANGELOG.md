# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- Restored the deprecated SFB1153 and SFB1368 `ckan.root_path` organization
  fallback for deployments targeting the original LUH repository. Explicit
  `ckanext.dataset_transfer.target_organization` configuration remains
  preferred and is required for custom destinations and TRR375.
