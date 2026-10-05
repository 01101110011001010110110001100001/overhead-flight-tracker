# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Talks to OpenSky to get plane positions. It handles the login (OAuth2),
# refreshes the access token when it's about to expire (or if the API says it's
# expired), asks for planes in a box, and flags when we're being rate-limited so
# the main loop can slow down.
#
# Docs: https://openskynetwork.github.io/opensky-api/rest.html
# No hardware imports -- just needs a requests session and time.monotonic().

import time

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/"
    "opensky-network/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"

# Refresh the token this many seconds BEFORE it actually expires, so a request
# never goes out with a token that dies mid-flight. (Tokens last ~30 minutes.)
TOKEN_RENEW_MARGIN_S = 60
DEFAULT_TOKEN_LIFETIME_S = 1800  # 30 min, used if the server omits expires_in


class OpenSkyError(Exception):
    """Any non-recoverable-in-one-call OpenSky problem (auth, bad response)."""


class RateLimited(OpenSkyError):
    """HTTP 429. `retry_after` is seconds to wait (None if not provided)."""

    def __init__(self, retry_after=None):
        super().__init__("rate limited")
        self.retry_after = retry_after


class OpenSkyClient:
    def __init__(self, requests_session, client_id, client_secret):
        self._requests = requests_session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token = None
        self._token_expiry = 0.0  # time.monotonic() value after which to renew

    # --- OAuth2 ----------------------------------------------------------
    def _fetch_token(self):
        """Exchange client_id/secret for a fresh access token."""
        # NOTE: we never print the secret or the token.
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        response = None
        try:
            response = self._requests.post(TOKEN_URL, data=data)
            if response.status_code != 200:
                raise OpenSkyError(
                    "token request failed: HTTP {}".format(response.status_code))
            payload = response.json()
        finally:
            if response is not None:
                response.close()  # free the socket buffer

        token = payload.get("access_token")
        if not token:
            raise OpenSkyError("token response had no access_token")
        lifetime = payload.get("expires_in", DEFAULT_TOKEN_LIFETIME_S)
        self._token = token
        self._token_expiry = time.monotonic() + lifetime - TOKEN_RENEW_MARGIN_S
        print("OpenSky: obtained access token (valid ~{}s)".format(lifetime))

    def _ensure_token(self):
        """Make sure we have a currently-valid token, renewing if needed."""
        if self._token is None or time.monotonic() >= self._token_expiry:
            self._fetch_token()
        return self._token

    # --- States ----------------------------------------------------------
    def get_states(self, bbox):
        """Fetch aircraft state vectors inside `bbox`.

        `bbox` is a dict with keys lamin, lamax, lomin, lomax (degrees).
        Returns (report_time, states):
          report_time -> int Unix seconds that OpenSky stamped the response with
                        (use this as "now" for staleness checks), or None.
          states      -> list of state-vector lists (possibly empty).

        Raises RateLimited on HTTP 429, OpenSkyError on other failures.
        Transparently refreshes the token once on a 401.
        """
        params = (
            "lamin={lamin}&lomin={lomin}&lamax={lamax}&lomax={lomax}".format(**bbox)
        )
        url = "{}?{}".format(STATES_URL, params)

        # Try with the current token; on 401, refresh once and retry.
        for attempt in (1, 2):
            token = self._ensure_token()
            headers = {"Authorization": "Bearer " + token}
            response = None
            try:
                response = self._requests.get(url, headers=headers)
                status = response.status_code

                if status == 200:
                    payload = response.json()
                    report_time = payload.get("time")
                    states = payload.get("states")
                    return report_time, (states if states else [])

                if status == 401 and attempt == 1:
                    # Token likely expired early; force a refresh and retry once.
                    print("OpenSky: 401, refreshing token and retrying")
                    self._token = None
                    continue

                if status == 429:
                    raise RateLimited(_retry_after_seconds(response))

                raise OpenSkyError("states request failed: HTTP {}".format(status))
            finally:
                if response is not None:
                    response.close()

        # Both attempts fell through (e.g. 401 twice).
        raise OpenSkyError("states request failed: unauthorized after refresh")


def _retry_after_seconds(response):
    """Parse a Retry-After header (seconds form) if present; else None."""
    try:
        value = response.headers.get("Retry-After")
    except (AttributeError, KeyError):
        value = None
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
