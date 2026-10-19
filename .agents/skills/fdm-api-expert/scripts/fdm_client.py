"""Minimal FDM REST API client used by the fdm-api-expert skill.

Goals:
- Load credentials from .env (never log them).
- Provide one obvious helper per workflow step so callers do not have to
  remember endpoint shapes or URL-encoding rules.

The client deliberately stays tiny and dependency-free (stdlib only) so it
can run in any agent environment without an extra install step.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


# How long any single FDM HTTP call may block before we give up. Without this,
# urllib.urlopen() waits forever, which silently hangs the whole agent turn when
# the network or VPN/proxy stalls. Override via FDM_HTTP_TIMEOUT (seconds).
def _http_timeout() -> float:
    try:
        return float(os.environ.get("FDM_HTTP_TIMEOUT", "60"))
    except (TypeError, ValueError):
        return 60.0


class FdmError(RuntimeError):
    pass


def _read_env(path: str) -> Dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Values may be quoted."""
    out: Dict[str, str] = {}
    if not os.path.exists(path):
        raise FdmError(f".env file not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            out[k.strip()] = v
    return out


class FdmClient:
    REQUIRED_KEYS = ("FDM_API_BASE_URL", "FDM_API_USERNAME", "FDM_API_PASSWORD")

    def __init__(self, env_path: str = ".env"):
        env = _read_env(env_path)
        missing = [k for k in self.REQUIRED_KEYS if not env.get(k)]
        if missing:
            raise FdmError(f".env missing required variables: {missing}")
        self.base = env["FDM_API_BASE_URL"]
        if not self.base.endswith("/"):
            self.base += "/"
        self._user = env["FDM_API_USERNAME"]
        self._pwd = env["FDM_API_PASSWORD"]
        self._token: Optional[str] = None

    # ---------- low level ----------
    def _request(self, method: str, path: str, body: Any = None,
                 headers: Optional[Dict[str, str]] = None) -> Any:
        url = self.base + path.lstrip("/")
        data = None
        h = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        if self._token and (not headers or "Authorization" not in headers):
            h["Authorization"] = f"Bearer {self._token}"
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=_http_timeout()) as resp:
                raw = resp.read()
                if not raw:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype:
                    return json.loads(raw)
                return raw.decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            if e.code in (401, 403):
                raise FdmError(
                    f"FDM authentication failed (HTTP {e.code}) for {method} {url}. "
                    f"Check FDM_API_USERNAME/FDM_API_PASSWORD in .env. :: {detail}"
                ) from None
            raise FdmError(f"HTTP {e.code} {method} {url} :: {detail}") from None
        except (socket.timeout, TimeoutError) as e:
            raise FdmError(
                f"FDM request timed out after {_http_timeout():.0f}s: {method} {url}. "
                f"The service may be unreachable from this network. ({e})"
            ) from None
        except urllib.error.URLError as e:
            raise FdmError(
                f"FDM network error for {method} {url}: {e.reason}. "
                f"Check connectivity/VPN/proxy to FDM_API_BASE_URL."
            ) from None

    # ---------- auth ----------
    def login(self) -> str:
        body = {"username": self._user, "password": self._pwd}
        token = self._request("POST", "Users/Login", body=body)
        if isinstance(token, str):
            token = token.strip().strip('"')
        if not token:
            raise FdmError("Login returned empty token")
        self._token = token
        return token

    # ---------- search / read ----------
    def search_finished_product(self, gcas: str) -> Dict[str, Any]:
        return self._request("GET", f"FinishedProducts/Search/{urllib.parse.quote(str(gcas))}")

    def resolve_unique_id(self, gcas: str) -> List[Dict[str, Any]]:
        """Return a flattened list of {uniqueId, identifier, revision, type, description, group}.

        Caller picks one when multiple are returned.
        """
        data = self.search_finished_product(gcas)
        out = []
        for grp in (data.get("groups") or []):
            for item in (grp.get("specifications") or []):
                sp = item.get("specification") or {}
                out.append({
                    "uniqueId": sp.get("uniqueId"),
                    "identifier": sp.get("identifier"),
                    "revision": sp.get("revision"),
                    "type": sp.get("type"),
                    "description": sp.get("description"),
                    "group": grp.get("name"),
                    "fpmStatus": item.get("fpmStatus"),
                })
        return out

    def get_all_finished_products_optimized(self, group: str = "Digital Specs",
                                            fpm_status: str = "") -> List[Dict[str, Any]]:
        """List FPPs (the catalog endpoint).

        Returns a potentially large array (10k+). Caller is responsible for
        filtering. The endpoint already accepts an empty `fpmStatus` to mean
        "any status".
        """
        qs = urllib.parse.urlencode({"group": group, "fpmStatus": fpm_status})
        data = self._request("GET", f"FinishedProducts/GetAllOptimized?{qs}")
        return data or []

    def get_specification(self, unique_id: str) -> Dict[str, Any]:
        enc = urllib.parse.quote(unique_id)
        return self._request("GET", f"Specifications/{enc}")

    # ---------- search / filter ----------
    def search_specifications(self, *,
                              last_download_gt: Optional[str] = None,
                              last_download_lt: Optional[str] = None,
                              modified_gt: Optional[str] = None,
                              modified_lt: Optional[str] = None,
                              initial_download_gt: Optional[str] = None,
                              initial_download_lt: Optional[str] = None,
                              types: Optional[List[str]] = None,
                              ip_class: Optional[str] = None,
                              ) -> List[Dict[str, Any]]:
        """Server-side filtered search via GET /Specifications/search.

        Date parameters are ISO 8601 strings (e.g. '2026-06-03T00:00:00').
        ``types`` can be e.g. ['Finished Product Part'].
        """
        params: List[tuple] = []
        if last_download_gt:
            params.append(("lastDownload.gt", last_download_gt))
        if last_download_lt:
            params.append(("lastDownload.lt", last_download_lt))
        if modified_gt:
            params.append(("modified.gt", modified_gt))
        if modified_lt:
            params.append(("modified.lt", modified_lt))
        if initial_download_gt:
            params.append(("initialDownload.gt", initial_download_gt))
        if initial_download_lt:
            params.append(("initialDownload.lt", initial_download_lt))
        if types:
            for t in types:
                params.append(("types", t))
        if ip_class:
            params.append(("IpClass", ip_class))
        qs = urllib.parse.urlencode(params)
        data = self._request("GET", f"Specifications/search?{qs}")
        if isinstance(data, dict):
            return data.get("results") or data.get("items") or []
        return data or []

    def get_change_identification(self, start_date: str, end_date: str,
                                  spec_type: Optional[str] = None,
                                  part_types: Optional[List[str]] = None,
                                  ) -> List[Dict[str, Any]]:
        """GET /ChangeIdentification — specs changed in a date range."""
        params: List[tuple] = [
            ("startDate", start_date),
            ("endDate", end_date),
        ]
        if spec_type:
            params.append(("type", spec_type))
        if part_types:
            for pt in part_types:
                params.append(("partTypes", pt))
        qs = urllib.parse.urlencode(params)
        data = self._request("GET", f"ChangeIdentification?{qs}")
        return data or []

    # ---------- parameters ----------
    def get_parameters(self, unique_id: str) -> List[Dict[str, Any]]:
        enc = urllib.parse.quote(unique_id)
        return self._request("GET", f"Specifications/{enc}/Parameters") or []

    def upsert_parameter(self, unique_id: str, key: str, value: Any,
                         data_type: int, exists: Optional[bool] = None) -> Any:
        """POST when the parameter is new; PUT when it already exists.

        Pass `exists` if you have already fetched the parameter list and know
        the answer; otherwise this will GET first to decide.
        """
        if exists is None:
            existing = {p.get("key") for p in self.get_parameters(unique_id)}
            exists = key in existing
        method = "PUT" if exists else "POST"
        enc = urllib.parse.quote(unique_id)
        body = {"parameter": {"key": key, "value": value, "dataType": data_type}}
        return self._request(method, f"Specifications/{enc}/Parameters", body=body)

    def delete_parameter(self, unique_id: str, key: str,
                         data_type: int = 0) -> Any:
        enc = urllib.parse.quote(unique_id)
        body = {"parameter": {"key": key, "value": None, "dataType": data_type}}
        return self._request("DELETE", f"Specifications/{enc}/Parameters", body=body)


def main(argv: List[str]) -> int:
    """tiny smoke test: `python fdm_client.py 80848203`"""
    if len(argv) < 2:
        print("usage: fdm_client.py <gcas>", file=sys.stderr)
        return 2
    gcas = argv[1]
    env_path = os.environ.get("FDM_ENV", ".env")
    c = FdmClient(env_path=env_path)
    c.login()
    matches = c.resolve_unique_id(gcas)
    if not matches:
        print(f"no match for {gcas}")
        return 1
    print(json.dumps(matches, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
