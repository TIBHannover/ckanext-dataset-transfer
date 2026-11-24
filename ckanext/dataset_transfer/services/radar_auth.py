# encoding: utf-8

"""Server-side RADAR technical-account authentication."""

import os
import time
from urllib.parse import urlparse

import requests


class RadarAuthConfigError(Exception):
    pass


class RadarAuthenticationError(Exception):
    pass


class RadarTokenProvider(object):
    """Acquire and cache a RADAR bearer token for one publication transfer."""

    SAFETY_MARGIN_SECONDS = 30
    DEFAULT_TIMEOUT = 30
    SETTINGS = {
        "clientId": (
            "ckanext.dataset_transfer.radar.client_id",
            "CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_ID",
        ),
        "clientSecret": (
            "ckanext.dataset_transfer.radar.client_secret",
            "CKANEXT_DATASET_TRANSFER_RADAR_CLIENT_SECRET",
        ),
        "redirectUrl": (
            "ckanext.dataset_transfer.radar.redirect_url",
            "CKANEXT_DATASET_TRANSFER_RADAR_REDIRECT_URL",
        ),
        "userName": (
            "ckanext.dataset_transfer.radar.user_name",
            "CKANEXT_DATASET_TRANSFER_RADAR_USER_NAME",
        ),
        "userPassword": (
            "ckanext.dataset_transfer.radar.user_password",
            "CKANEXT_DATASET_TRANSFER_RADAR_USER_PASSWORD",
        ),
    }

    def __init__(self, config, request_session=None, clock=None):
        self.config = config
        self.requests = request_session or requests
        self.clock = clock or time.time
        self.context_url = self._read(
            "ckanext.dataset_transfer.radar.context_url",
            "CKANEXT_DATASET_TRANSFER_RADAR_CONTEXT_URL",
        ).rstrip("/")
        parsed = urlparse(self.context_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RadarAuthConfigError(
                "RADAR authentication requires a valid HTTPS context URL."
            )
        self.token_url = self.context_url + "/api/tokens"
        self.payload = {}
        missing = []
        for payload_key, (config_key, env_key) in self.SETTINGS.items():
            value = self._read(config_key, env_key, required=False)
            if not value or self._is_unresolved(value):
                missing.append(config_key)
            else:
                self.payload[payload_key] = value
        if missing:
            raise RadarAuthConfigError("RADAR authentication is not configured.")
        self._access_token = None
        self._expires_at = None

    def get_valid_access_token(self):
        now = self.clock()
        if self._access_token and (
            self._expires_at is None or now < self._expires_at
        ):
            return self._access_token
        self._authenticate(now)
        return self._access_token

    def mark_reauthentication_required(self):
        self._access_token = None
        self._expires_at = None

    def _authenticate(self, now):
        try:
            response = self.requests.post(
                self.token_url,
                json=self.payload,
                timeout=self.DEFAULT_TIMEOUT,
            )
        except requests.Timeout:
            raise RadarAuthenticationError(
                "RADAR authentication timed out. Please try again later."
            )
        except requests.RequestException:
            raise RadarAuthenticationError(
                "RADAR authentication service is unavailable. Please try again later."
            )
        if response.status_code in (401, 403):
            raise RadarAuthenticationError(
                "RADAR authentication failed. Please check the configured credentials."
            )
        if not 200 <= response.status_code < 300:
            raise RadarAuthenticationError(
                "RADAR authentication service returned HTTP {}.".format(
                    response.status_code
                )
            )
        try:
            body = response.json()
        except (TypeError, ValueError):
            body = None
        if not isinstance(body, dict):
            raise RadarAuthenticationError(
                "RADAR authentication returned an invalid response."
            )
        token = body.get("accessToken") or body.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise RadarAuthenticationError(
                "RADAR authentication returned an invalid response."
            )
        self._access_token = token.strip()
        expires_in = body.get("expiresIn", body.get("expires_in"))
        if expires_in is None:
            self._expires_at = None
            return
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            self.mark_reauthentication_required()
            raise RadarAuthenticationError(
                "RADAR authentication returned an invalid response."
            )
        if lifetime <= 0:
            self.mark_reauthentication_required()
            raise RadarAuthenticationError(
                "RADAR authentication returned an expired token."
            )
        margin = min(self.SAFETY_MARGIN_SECONDS, lifetime * 0.1)
        self._expires_at = now + lifetime - margin

    def _read(self, config_key, env_key, required=True):
        value = self.config.get(config_key)
        if value is None or not str(value).strip():
            value = os.environ.get(env_key)
        value = str(value).strip() if value is not None else ""
        if required and (not value or self._is_unresolved(value)):
            raise RadarAuthConfigError("RADAR authentication is not configured.")
        return value

    @staticmethod
    def _is_unresolved(value):
        value = str(value).strip()
        return (
            (value.startswith("${") and value.endswith("}"))
            or (value.startswith("{{") and value.endswith("}}"))
        )
