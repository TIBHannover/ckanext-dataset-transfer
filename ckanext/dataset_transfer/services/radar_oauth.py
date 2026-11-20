# encoding: utf-8

import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import ckan.plugins.toolkit as toolkit
import redis
import requests
from cryptography.fernet import Fernet, InvalidToken
from redis.exceptions import RedisError


class RadarOAuthError(Exception):
    def __init__(
        self, message, status=None, flow_consumed=False, dataset_name=None,
        dataset_id=None, attempt_id=None
    ):
        super(RadarOAuthError, self).__init__(message)
        self.status = status
        self.flow_consumed = flow_consumed
        self.dataset_name = dataset_name
        self.dataset_id = dataset_id
        self.attempt_id = attempt_id


class RadarOAuthConfigError(RadarOAuthError):
    pass


class RadarOAuthStateError(RadarOAuthError):
    pass


class RadarReauthenticationRequired(RadarOAuthError):
    pass


class RadarOAuthTemporaryError(RadarOAuthError):
    pass


class RadarOAuthAttemptClaimed(RadarOAuthError):
    pass


class RadarUserTokenProvider(object):
    def __init__(
        self, oauth_service, user_id, dataset_id, session_binding, attempt_id
    ):
        self.oauth_service = oauth_service
        self.user_id = user_id
        self.dataset_id = dataset_id
        self.session_binding = session_binding
        self.attempt_id = attempt_id

    def get_valid_access_token(self):
        return self.oauth_service.get_valid_access_token(
            self.user_id,
            self.dataset_id,
            self.session_binding,
            self.attempt_id,
            require_claimed=True,
        )

    def mark_reauthentication_required(self):
        self.oauth_service.mark_reauthentication_required(
            self.user_id,
            self.dataset_id,
            self.session_binding,
            self.attempt_id,
        )


class RadarOAuthService(object):
    STATE_TTL_SECONDS = 600
    ATTEMPT_TTL_SECONDS = 3600
    ACTIVE_ATTEMPT_TTL_SECONDS = 7200
    TOKEN_TIMEOUT_SECONDS = 30
    REFRESH_MARGIN_SECONDS = 300
    LOCK_TIMEOUT_SECONDS = 30
    KEY_PREFIX = "ckanext:dataset_transfer:radar:oauth"
    GETDEL_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""

    def __init__(
        self, config=None, request_session=None, now=None, redis_client=None
    ):
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
            "ckanext.dataset_transfer.radar.oauth_state_ttl",
            self.STATE_TTL_SECONDS,
        )
        self.attempt_ttl = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_attempt_ttl",
            self.ATTEMPT_TTL_SECONDS,
        )
        self.active_attempt_ttl = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_active_attempt_ttl",
            self.ACTIVE_ATTEMPT_TTL_SECONDS,
        )
        if self.active_attempt_ttl < self.attempt_ttl:
            raise RadarOAuthConfigError(
                "RADAR OAuth active-attempt TTL must not be shorter than "
                "the review-attempt TTL."
            )
        self.timeout = self._positive_integer(
            "ckanext.dataset_transfer.radar.oauth_timeout",
            self.TOKEN_TIMEOUT_SECONDS,
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
        self.redis = redis_client or self._create_redis_client()
        try:
            self.redis.ping()
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    @classmethod
    def configuration_status(cls, config=None):
        try:
            cls(config=config)
            return {"configured": True, "message": ""}
        except RadarOAuthConfigError:
            return {
                "configured": False,
                "message": (
                    "RADAR4Ing temporary authentication is not configured on "
                    "this CKAN instance."
                ),
            }
        except RadarOAuthTemporaryError:
            return {
                "configured": False,
                "temporarily_unavailable": True,
                "message": (
                    "RADAR4Ing temporary authentication storage is unavailable."
                ),
            }

    def authorization_url(
        self, user_id, dataset_id, dataset_name, session_binding=None
    ):
        if not user_id or not dataset_id or not dataset_name:
            raise RadarOAuthError("A CKAN user and dataset are required.")
        state = secrets.token_urlsafe(48)
        state_id = self._hash(state)
        attempt_id = secrets.token_urlsafe(32)
        session_binding = session_binding or secrets.token_urlsafe(48)
        code_verifier = secrets.token_urlsafe(64) if self.pkce_enabled else ""
        flow = {
            "user_id": str(user_id),
            "dataset_id": str(dataset_id),
            "dataset_name": str(dataset_name)[:200],
            "environment": self.environment,
            "session_binding_hash": self._hash(session_binding),
            "code_verifier": code_verifier,
            "attempt_id": attempt_id,
            "created_at": self._timestamp(),
        }
        try:
            stored = self.redis.set(
                self._state_key(state_id),
                self._seal_json(flow),
                ex=self.state_ttl,
                nx=True,
            )
            if not stored:
                raise RadarOAuthTemporaryError(
                    "RADAR OAuth state could not be created."
                )
        except RadarOAuthError:
            raise
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error
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
        return (
            self._url_with_query(self.authorize_url, parameters),
            session_binding,
            state_id,
        )

    def complete_authorization(
        self, user_id, state, session_binding, code=None, provider_error=None
    ):
        if not state or not session_binding:
            raise RadarOAuthStateError("RADAR OAuth state is missing or invalid.")
        state_id = self._hash(state)
        try:
            sealed_flow = self.redis.eval(
                self.GETDEL_SCRIPT, 1, self._state_key(state_id)
            )
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error
        if not sealed_flow:
            raise RadarOAuthStateError(
                "RADAR OAuth state is invalid, expired, or already used."
            )
        flow = self._open_json(sealed_flow, state_error=True)
        details = {
            "flow_consumed": True,
            "dataset_name": flow.get("dataset_name"),
            "dataset_id": flow.get("dataset_id"),
            "attempt_id": flow.get("attempt_id"),
        }
        if (
            not hmac.compare_digest(str(flow.get("user_id", "")), str(user_id))
            or flow.get("environment") != self.environment
        ):
            raise RadarOAuthStateError(
                "RADAR OAuth state belongs to another user or environment.",
                **details
            )
        if not hmac.compare_digest(
            str(flow.get("session_binding_hash", "")),
            self._hash(session_binding),
        ):
            raise RadarOAuthStateError(
                "RADAR OAuth session binding is invalid.", **details
            )
        if provider_error:
            raise RadarOAuthError(
                "RADAR authorization was denied or cancelled.", **details
            )
        if not code:
            raise RadarOAuthError(
                "RADAR did not return an authorization code.", **details
            )
        try:
            token_data = self._exchange_code(
                code, str(flow.get("code_verifier") or "")
            )
        except RadarOAuthError as error:
            error.flow_consumed = True
            error.dataset_name = flow.get("dataset_name")
            error.dataset_id = flow.get("dataset_id")
            error.attempt_id = flow.get("attempt_id")
            raise
        self._save_token_response(
            user_id=user_id,
            dataset_id=flow["dataset_id"],
            dataset_name=flow["dataset_name"],
            session_binding=session_binding,
            attempt_id=flow["attempt_id"],
            token_data=token_data,
        )
        return {
            "dataset_id": flow["dataset_id"],
            "dataset_name": flow["dataset_name"],
            "attempt_id": flow["attempt_id"],
            "session_binding": session_binding,
        }

    def connection_status(
        self, user_id, dataset_id, session_binding, attempt_id,
        refresh_if_needed=False
    ):
        if not attempt_id or not session_binding:
            return {"connected": False, "requires_reauthentication": False}
        record = self._load_and_validate_attempt(
            user_id, dataset_id, session_binding, attempt_id,
            missing_ok=True,
        )
        if not record:
            return {
                "connected": False,
                "requires_reauthentication": False,
                "expired": True,
            }
        if record.get("requires_reauthentication"):
            return {"connected": False, "requires_reauthentication": True}
        if refresh_if_needed:
            try:
                self.get_valid_access_token(
                    user_id, dataset_id, session_binding, attempt_id
                )
            except RadarReauthenticationRequired:
                return {"connected": False, "requires_reauthentication": True}
            except RadarOAuthTemporaryError:
                return {
                    "connected": False,
                    "requires_reauthentication": False,
                    "temporarily_unavailable": True,
                }
        return {"connected": True, "requires_reauthentication": False}

    def token_provider(
        self, user_id, dataset_id, session_binding, attempt_id
    ):
        return RadarUserTokenProvider(
            self, user_id, dataset_id, session_binding, attempt_id
        )

    def claim_attempt(self, user_id, dataset_id, session_binding, attempt_id):
        if not attempt_id:
            raise RadarReauthenticationRequired(
                "Authorize this dataset transfer with RADAR4Ing before publishing."
            )
        try:
            with self._attempt_lock(attempt_id):
                self._load_and_validate_attempt(
                    user_id, dataset_id, session_binding, attempt_id
                )
                claimed = self.redis.set(
                    self._claim_key(attempt_id),
                    secrets.token_urlsafe(24),
                    nx=True,
                    ex=self.active_attempt_ttl,
                )
                if not claimed:
                    raise RadarOAuthAttemptClaimed(
                        "This RADAR4Ing authorization is already being used."
                    )
                self.redis.expire(
                    self._attempt_key(attempt_id), self.active_attempt_ttl
                )
        except RadarOAuthError:
            raise
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def finish_attempt(self, attempt_id):
        if not attempt_id:
            return
        try:
            with self._attempt_lock(attempt_id):
                self.redis.delete(
                    self._attempt_key(attempt_id), self._claim_key(attempt_id)
                )
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary credentials could not be removed."
            ) from error

    def disconnect(
        self, user_id, dataset_id, session_binding, attempt_id
    ):
        if not attempt_id:
            return
        try:
            with self._attempt_lock(attempt_id):
                self._load_and_validate_attempt(
                    user_id, dataset_id, session_binding, attempt_id,
                    missing_ok=True,
                )
                if self.redis.exists(self._claim_key(attempt_id)):
                    raise RadarOAuthAttemptClaimed(
                        "An active RADAR4Ing publication cannot be disconnected."
                    )
                self.redis.delete(self._attempt_key(attempt_id))
        except RadarOAuthError:
            raise
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def get_valid_access_token(
        self, user_id, dataset_id, session_binding, attempt_id,
        require_claimed=False
    ):
        record = self._load_and_validate_attempt(
            user_id, dataset_id, session_binding, attempt_id
        )
        if require_claimed and not self._is_claimed(attempt_id):
            raise RadarOAuthAttemptClaimed(
                "This RADAR4Ing publication authorization has not been claimed."
            )
        if record.get("requires_reauthentication"):
            raise RadarReauthenticationRequired(
                "Your RADAR4Ing authorization has expired. Connect again."
            )
        if float(record["expires_at"]) > self._timestamp() + self.refresh_margin:
            return str(record["access_token"])
        return self._refresh(
            user_id, dataset_id, session_binding, attempt_id
        )

    def mark_reauthentication_required(
        self, user_id, dataset_id, session_binding, attempt_id
    ):
        try:
            with self._attempt_lock(attempt_id):
                record = self._load_and_validate_attempt(
                    user_id, dataset_id, session_binding, attempt_id,
                    missing_ok=True,
                )
                if record:
                    record["requires_reauthentication"] = True
                    self._save_attempt_preserving_ttl(attempt_id, record)
        except RadarOAuthError:
            raise
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def _refresh(self, user_id, dataset_id, session_binding, attempt_id):
        try:
            with self._attempt_lock(attempt_id):
                record = self._load_and_validate_attempt(
                    user_id, dataset_id, session_binding, attempt_id
                )
                if float(record["expires_at"]) > (
                    self._timestamp() + self.refresh_margin
                ):
                    return str(record["access_token"])
                refresh_token = str(record.get("refresh_token") or "")
                if not refresh_token:
                    return self._require_reauthentication(
                        attempt_id,
                        record,
                        "RADAR did not provide a refresh token. Connect again.",
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
                        attempt_id,
                        record,
                        "Your RADAR4Ing authorization has expired. Connect again.",
                    )
                token_data = self._token_response(
                    response, "RADAR token refresh failed."
                )
                record["access_token"] = token_data["access_token"]
                record["refresh_token"] = (
                    token_data.get("refresh_token") or refresh_token
                )
                record["expires_at"] = (
                    self._timestamp() + self._expires_in(token_data)
                )
                record["requires_reauthentication"] = False
                self._save_attempt_preserving_ttl(attempt_id, record)
                return token_data["access_token"]
        except RadarOAuthError:
            raise
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def _require_reauthentication(self, attempt_id, record, message):
        record["requires_reauthentication"] = True
        self._save_attempt_preserving_ttl(attempt_id, record)
        raise RadarReauthenticationRequired(message)

    def _save_token_response(
        self, user_id, dataset_id, dataset_name, session_binding, attempt_id,
        token_data
    ):
        record = {
            "user_id": str(user_id),
            "dataset_id": str(dataset_id),
            "dataset_name": str(dataset_name)[:200],
            "environment": self.environment,
            "session_binding_hash": self._hash(session_binding),
            "access_token": str(token_data["access_token"]),
            "refresh_token": str(token_data.get("refresh_token") or ""),
            "expires_at": self._timestamp() + self._expires_in(token_data),
            "created_at": self._timestamp(),
            "requires_reauthentication": False,
        }
        try:
            self.redis.set(
                self._attempt_key(attempt_id),
                self._seal_json(record),
                ex=self.attempt_ttl,
            )
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def _load_and_validate_attempt(
        self, user_id, dataset_id, session_binding, attempt_id,
        missing_ok=False
    ):
        if not attempt_id or not session_binding:
            if missing_ok:
                return None
            raise RadarReauthenticationRequired(
                "Authorize this dataset transfer with RADAR4Ing before publishing."
            )
        try:
            value = self.redis.get(self._attempt_key(attempt_id))
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error
        if not value:
            if missing_ok:
                return None
            raise RadarReauthenticationRequired(
                "Your RADAR4Ing authorization has expired. Connect again."
            )
        record = self._open_json(value)
        valid = (
            hmac.compare_digest(str(record.get("user_id", "")), str(user_id))
            and hmac.compare_digest(
                str(record.get("dataset_id", "")), str(dataset_id)
            )
            and record.get("environment") == self.environment
            and hmac.compare_digest(
                str(record.get("session_binding_hash", "")),
                self._hash(session_binding),
            )
        )
        if not valid:
            raise RadarReauthenticationRequired(
                "This RADAR4Ing authorization does not belong to this dataset "
                "and browser session."
            )
        return record

    def _save_attempt_preserving_ttl(self, attempt_id, record):
        ttl = self.redis.ttl(self._attempt_key(attempt_id))
        if ttl is None or ttl <= 0:
            raise RadarReauthenticationRequired(
                "Your RADAR4Ing authorization has expired. Connect again."
            )
        self.redis.set(
            self._attempt_key(attempt_id), self._seal_json(record), ex=ttl
        )

    def _is_claimed(self, attempt_id):
        try:
            return bool(self.redis.exists(self._claim_key(attempt_id)))
        except RedisError as error:
            raise RadarOAuthTemporaryError(
                "RADAR4Ing temporary authentication storage is unavailable."
            ) from error

    def _attempt_lock(self, attempt_id):
        return self.redis.lock(
            self._lock_key(attempt_id),
            timeout=self.LOCK_TIMEOUT_SECONDS,
            blocking_timeout=self.timeout,
        )

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

    def _create_redis_client(self):
        redis_url = self._setting("ckan.redis.url")
        if not redis_url:
            raise RadarOAuthConfigError(
                "CKAN Redis configuration is required for RADAR OAuth."
            )
        try:
            return redis.Redis.from_url(str(redis_url), decode_responses=False)
        except (RedisError, ValueError) as error:
            raise RadarOAuthConfigError(
                "CKAN Redis configuration is invalid for RADAR OAuth."
            ) from error

    def _seal_json(self, value):
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.fernet.encrypt(payload)

    def _open_json(self, value, state_error=False):
        try:
            if isinstance(value, str):
                value = value.encode("ascii")
            payload = self.fernet.decrypt(value)
            result = json.loads(payload.decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("invalid payload")
            return result
        except (InvalidToken, ValueError, TypeError, UnicodeError) as error:
            error_type = (
                RadarOAuthStateError
                if state_error
                else RadarReauthenticationRequired
            )
            raise error_type(
                "RADAR4Ing temporary authorization data is invalid. Connect again."
            ) from error

    def _state_key(self, state_id):
        return "{}:{}:state:{}".format(
            self.KEY_PREFIX, self.environment, state_id
        )

    def _attempt_key(self, attempt_id):
        return "{}:{}:attempt:{}".format(
            self.KEY_PREFIX, self.environment, attempt_id
        )

    def _claim_key(self, attempt_id):
        return "{}:{}:claim:{}".format(
            self.KEY_PREFIX, self.environment, attempt_id
        )

    def _lock_key(self, attempt_id):
        return "{}:{}:lock:{}".format(
            self.KEY_PREFIX, self.environment, attempt_id
        )

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
        raise RadarOAuthConfigError(
            "Missing RADAR OAuth configuration: {}".format(key)
        )

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

    def _timestamp(self):
        return self.now().replace(tzinfo=None).timestamp()

    @staticmethod
    def _hash(value):
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _url_with_query(url, parameters):
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(parameters)
        return urlunparse(parsed._replace(query=urlencode(query)))
