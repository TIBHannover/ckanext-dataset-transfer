# encoding: utf-8

import base64
import datetime
import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import ckan.plugins.toolkit as toolkit
from ckan.model import meta
from cryptography.fernet import Fernet, InvalidToken

from ckanext.dataset_transfer.models.radar_oauth import (
    RadarOAuthState,
    RadarOAuthToken,
)


class RadarOAuthError(Exception):
    def __init__(
        self, message, status=None, flow_consumed=False, dataset_name=None
    ):
        super(RadarOAuthError, self).__init__(message)
        self.status = status
        self.flow_consumed = flow_consumed
        self.dataset_name = dataset_name


class RadarOAuthConfigError(RadarOAuthError):
    pass


class RadarOAuthStateError(RadarOAuthError):
    pass


class RadarReauthenticationRequired(RadarOAuthError):
    pass


class RadarOAuthTemporaryError(RadarOAuthError):
    pass


class RadarUserTokenProvider(object):
    def __init__(self, oauth_service, user_id):
        self.oauth_service = oauth_service
        self.user_id = user_id

    def get_valid_access_token(self):
        return self.oauth_service.get_valid_access_token(self.user_id)

    def mark_reauthentication_required(self):
        self.oauth_service.mark_reauthentication_required(self.user_id)


class RadarOAuthService(object):
    STATE_TTL_SECONDS = 600
    TOKEN_TIMEOUT_SECONDS = 30
    REFRESH_MARGIN_SECONDS = 300

    def __init__(self, config=None, request_session=None, now=None):
        self.config = config or toolkit.config
        self.requests = request_session or requests
        self.now = now or datetime.datetime.utcnow
        self.environment = self._required(
            "ckanext.dataset_transfer.radar.oauth_environment"
        )
        if not re.match(r"^[A-Za-z0-9_.-]{1,80}$", self.environment):
            raise RadarOAuthConfigError("RADAR OAuth environment is invalid.")
        self.authorize_url = self._https_url(
            "ckanext.dataset_transfer.radar.oauth_authorize_url"
        )
        self.token_url = self._https_url(
            "ckanext.dataset_transfer.radar.oauth_token_url"
        )
        self.refresh_url = self._https_url(
            "ckanext.dataset_transfer.radar.oauth_refresh_url"
        )
        self.callback_url = self._https_url(
            "ckanext.dataset_transfer.radar.oauth_callback_url"
        )
        self.context_url = self._https_url(
            "ckanext.dataset_transfer.radar.context_url"
        )
        self.client_id = self._required(
            "ckanext.dataset_transfer.radar.client_id"
        )
        self.client_secret = self._required(
            "ckanext.dataset_transfer.radar.client_secret"
        )
        self.refresh_mode = self._required(
            "ckanext.dataset_transfer.radar.oauth_refresh_mode"
        )
        if self.refresh_mode not in ("radar_api", "oauth_token"):
            raise RadarOAuthConfigError(
                "RADAR OAuth refresh mode must be radar_api or oauth_token."
            )
        self.pkce_enabled = self._boolean(
            "ckanext.dataset_transfer.radar.oauth_pkce_enabled", False
        )
        self.state_ttl = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_state_ttl", self.STATE_TTL_SECONDS
        )
        self.timeout = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_timeout", self.TOKEN_TIMEOUT_SECONDS
        )
        self.refresh_margin = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_refresh_margin",
            self.REFRESH_MARGIN_SECONDS,
            allow_zero=True,
        )
        encryption_key = self._required(
            "ckanext.dataset_transfer.radar.oauth_token_encryption_key"
        )
        try:
            self.fernet = Fernet(encryption_key.encode("ascii"))
        except (ValueError, TypeError, UnicodeError) as error:
            raise RadarOAuthConfigError(
                "RADAR OAuth token encryption key is invalid."
            ) from error
        self._validate_environment_hosts()

    @classmethod
    def configuration_status(cls, config=None):
        try:
            cls(config=config)
            return {"configured": True, "message": ""}
        except RadarOAuthConfigError:
            return {
                "configured": False,
                "message": (
                    "RADAR4Ing account connections are not configured on this "
                    "CKAN instance."
                ),
            }

    def authorization_url(self, user_id, dataset_name, session_binding=None):
        if not user_id or not dataset_name:
            raise RadarOAuthError("A CKAN user and dataset are required.")
        state = secrets.token_urlsafe(48)
        session_binding = session_binding or secrets.token_urlsafe(48)
        code_verifier = secrets.token_urlsafe(64) if self.pkce_enabled else ""
        now = self.now()
        RadarOAuthState.delete_open_for_user(user_id, self.environment)
        flow = RadarOAuthState(
            ckan_user_id=user_id,
            radar_environment=self.environment,
            state_hash=self._hash(state),
            session_binding_hash=self._hash(session_binding),
            code_verifier_encrypted=self._encrypt_optional(code_verifier),
            dataset_name=str(dataset_name)[:200],
            created_at=now,
        )
        flow.save()
        parameters = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.callback_url,
            "state": state,
        }
        if code_verifier:
            digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
            parameters["code_challenge"] = base64.urlsafe_b64encode(
                digest
            ).decode("ascii").rstrip("=")
            parameters["code_challenge_method"] = "S256"
        return self._url_with_query(self.authorize_url, parameters), session_binding

    def complete_authorization(
        self, user_id, state, session_binding, code=None, provider_error=None
    ):
        if not state or not session_binding:
            raise RadarOAuthStateError("RADAR OAuth state is missing or invalid.")
        state_hash = self._hash(state)
        flow = RadarOAuthState.get_by_state_hash(
            state_hash, for_update=True
        )
        if not flow or flow.used_at is not None:
            raise RadarOAuthStateError("RADAR OAuth state is invalid or already used.")
        if not hmac.compare_digest(flow.state_hash, state_hash):
            raise RadarOAuthStateError("RADAR OAuth state is invalid.")
        if flow.ckan_user_id != user_id or flow.radar_environment != self.environment:
            raise RadarOAuthStateError("RADAR OAuth state belongs to another session.")
        if not hmac.compare_digest(
            flow.session_binding_hash, self._hash(session_binding)
        ):
            raise RadarOAuthStateError("RADAR OAuth session binding is invalid.")
        if flow.created_at < self.now() - datetime.timedelta(seconds=self.state_ttl):
            flow.used_at = self.now()
            flow.save()
            raise RadarOAuthStateError(
                "RADAR OAuth state has expired.",
                flow_consumed=True,
                dataset_name=flow.dataset_name,
            )
        flow.used_at = self.now()
        flow.save()
        if provider_error:
            raise RadarOAuthError(
                "RADAR authorization was denied or cancelled.",
                flow_consumed=True,
                dataset_name=flow.dataset_name,
            )
        if not code:
            raise RadarOAuthError(
                "RADAR did not return an authorization code.",
                flow_consumed=True,
                dataset_name=flow.dataset_name,
            )
        code_verifier = self._decrypt_optional(flow.code_verifier_encrypted)
        try:
            token_data = self._exchange_code(code, code_verifier)
        except RadarOAuthError as error:
            error.flow_consumed = True
            error.dataset_name = flow.dataset_name
            raise
        self._save_token_response(user_id, token_data)
        return flow.dataset_name

    def connection_status(self, user_id, refresh_if_needed=True):
        record = RadarOAuthToken.get_by_user_environment(
            user_id, self.environment
        )
        if not record or record.requires_reauthentication:
            return {"connected": False, "requires_reauthentication": bool(record)}
        if refresh_if_needed:
            try:
                self.get_valid_access_token(user_id)
            except RadarReauthenticationRequired:
                return {"connected": False, "requires_reauthentication": True}
            except RadarOAuthTemporaryError:
                return {
                    "connected": False,
                    "requires_reauthentication": False,
                    "temporarily_unavailable": True,
                }
        return {"connected": True, "requires_reauthentication": False}

    def token_provider(self, user_id):
        return RadarUserTokenProvider(self, user_id)

    def get_valid_access_token(self, user_id):
        record = RadarOAuthToken.get_by_user_environment(
            user_id, self.environment, for_update=True
        )
        if not record or record.requires_reauthentication:
            raise RadarReauthenticationRequired(
                "Connect your RADAR4Ing account before publishing."
            )
        if record.expires_at > self.now() + datetime.timedelta(
            seconds=self.refresh_margin
        ):
            return self._decrypt_required(record.access_token_encrypted)
        return self._refresh(record)

    def disconnect(self, user_id):
        record = RadarOAuthToken.get_by_user_environment(
            user_id, self.environment, for_update=True
        )
        if record:
            record.delete()
        RadarOAuthState.delete_open_for_user(user_id, self.environment)
        meta.Session.flush()

    def mark_reauthentication_required(self, user_id):
        record = RadarOAuthToken.get_by_user_environment(
            user_id, self.environment, for_update=True
        )
        if record:
            record.requires_reauthentication = True
            record.updated_at = self.now()
            record.save()

    def _exchange_code(self, code, code_verifier):
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.callback_url,
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        try:
            response = self.requests.post(
                self.token_url,
                auth=(self.client_id, self.client_secret),
                data=form,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise RadarOAuthTemporaryError(
                "RADAR token exchange is currently unavailable."
            ) from error
        return self._token_response(response, "RADAR token exchange failed.")

    def _refresh(self, record):
        refresh_token = self._decrypt_optional(record.refresh_token_encrypted)
        if not refresh_token:
            return self._require_reauthentication(
                record, "RADAR did not provide a refresh token. Reconnect your account."
            )
        try:
            if self.refresh_mode == "radar_api":
                response = self.requests.post(
                    self.refresh_url,
                    json={
                        "clientId": self.client_id,
                        "clientSecret": self.client_secret,
                        "refreshToken": refresh_token,
                    },
                    timeout=self.timeout,
                )
            else:
                response = self.requests.post(
                    self.token_url,
                    auth=(self.client_id, self.client_secret),
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=self.timeout,
                )
        except requests.RequestException as error:
            raise RadarOAuthTemporaryError(
                "RADAR token refresh is currently unavailable."
            ) from error
        if response.status_code in (400, 401, 403):
            return self._require_reauthentication(
                record, "Your RADAR4Ing connection has expired. Reconnect your account."
            )
        token_data = self._token_response(response, "RADAR token refresh failed.")
        if not token_data.get("refresh_token"):
            token_data["refresh_token"] = refresh_token
        self._apply_token_response(record, token_data)
        record.save()
        return token_data["access_token"]

    def _require_reauthentication(self, record, message):
        record.requires_reauthentication = True
        record.updated_at = self.now()
        record.save()
        raise RadarReauthenticationRequired(message)

    def _save_token_response(self, user_id, token_data):
        record = RadarOAuthToken.get_by_user_environment(
            user_id, self.environment, for_update=True
        )
        now = self.now()
        if not record:
            record = RadarOAuthToken(
                ckan_user_id=user_id,
                radar_environment=self.environment,
                connected_at=now,
            )
        self._apply_token_response(record, token_data)
        record.save()

    def _apply_token_response(self, record, token_data):
        expires_in = self._expires_in(token_data)
        record.access_token_encrypted = self._encrypt_required(
            token_data["access_token"]
        )
        record.refresh_token_encrypted = self._encrypt_optional(
            token_data.get("refresh_token")
        )
        record.expires_at = self.now() + datetime.timedelta(seconds=expires_in)
        record.updated_at = self.now()
        record.requires_reauthentication = False

    def _token_response(self, response, failure_message):
        if not 200 <= response.status_code < 300:
            if response.status_code == 429 or response.status_code >= 500:
                raise RadarOAuthTemporaryError(
                    "RADAR authentication is temporarily unavailable.",
                    status=response.status_code,
                )
            raise RadarOAuthError(failure_message, status=response.status_code)
        try:
            data = response.json()
        except (TypeError, ValueError) as error:
            raise RadarOAuthError(
                "RADAR returned an invalid token response."
            ) from error
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RadarOAuthError(
                "RADAR token response did not contain an access token."
            )
        self._expires_in(data)
        return {
            "access_token": str(data["access_token"]),
            "refresh_token": (
                str(data["refresh_token"]) if data.get("refresh_token") else ""
            ),
            "expires_in": data["expires_in"],
        }

    @staticmethod
    def _expires_in(data):
        try:
            expires_in = int(data.get("expires_in"))
        except (TypeError, ValueError) as error:
            raise RadarOAuthError(
                "RADAR token response did not contain a valid expiration."
            ) from error
        if expires_in <= 0:
            raise RadarOAuthError(
                "RADAR token response did not contain a valid expiration."
            )
        return expires_in

    def _encrypt_required(self, value):
        if not value:
            raise RadarOAuthError("RADAR returned an empty token.")
        return self.fernet.encrypt(str(value).encode("utf-8")).decode("ascii")

    def _encrypt_optional(self, value):
        return self._encrypt_required(value) if value else None

    def _decrypt_required(self, value):
        if not value:
            raise RadarReauthenticationRequired(
                "Your RADAR4Ing connection is incomplete. Reconnect your account."
            )
        try:
            return self.fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as error:
            raise RadarReauthenticationRequired(
                "Your RADAR4Ing connection cannot be read. Reconnect your account."
            ) from error

    def _decrypt_optional(self, value):
        return self._decrypt_required(value) if value else ""

    def _validate_environment_hosts(self):
        endpoint_hosts = {
            urlparse(value).hostname
            for value in (
                self.context_url,
                self.authorize_url,
                self.token_url,
                self.refresh_url,
            )
        }
        if len(endpoint_hosts) != 1:
            raise RadarOAuthConfigError(
                "RADAR OAuth endpoints do not match the configured environment."
            )
        endpoint_host = next(iter(endpoint_hosts))
        environment = self.environment.lower()
        if environment == "test" and endpoint_host != "test.radar-service.eu":
            raise RadarOAuthConfigError(
                "RADAR OAuth endpoints do not match the test environment."
            )
        if environment == "production" and endpoint_host == "test.radar-service.eu":
            raise RadarOAuthConfigError(
                "RADAR test endpoints cannot be used for the production environment."
            )

    def _https_url(self, key):
        value = self._required(key).rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise RadarOAuthConfigError(
                "{} must be an HTTPS URL without embedded credentials.".format(key)
            )
        return value

    def _required(self, key):
        value = self._setting(key)
        if value is not None and str(value).strip():
            return str(value).strip()
        raise RadarOAuthConfigError("Missing RADAR OAuth configuration: {}".format(key))

    def _setting(self, key, default=None):
        value = self.config.get(key)
        if value is not None and str(value).strip():
            return value
        value = os.environ.get(key.upper().replace(".", "_"))
        if value is not None and str(value).strip():
            return value
        return default

    def _boolean(self, key, default):
        value = str(self._setting(key, str(default))).strip().lower()
        if value in ("true", "1", "yes", "on"):
            return True
        if value in ("false", "0", "no", "off"):
            return False
        raise RadarOAuthConfigError("{} must be true or false.".format(key))

    def _positive_integer(self, key, default, allow_zero=False):
        try:
            value = int(self._setting(key, default))
        except (TypeError, ValueError) as error:
            raise RadarOAuthConfigError("{} must be an integer.".format(key)) from error
        if value < 0 or (value == 0 and not allow_zero):
            raise RadarOAuthConfigError("{} must be positive.".format(key))
        return value

    @staticmethod
    def _hash(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _url_with_query(url, parameters):
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(parameters)
        return urlunparse(parsed._replace(query=urlencode(query)))
