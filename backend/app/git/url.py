"""Clone-URL credential injection and redaction (no secrets in logs, Std §6).

``authenticated_url`` builds the credentialed clone URL used in the git command;
``redact_url`` strips userinfo for anything that gets logged or surfaced in an
error. Only http(s) URLs get a token; ssh/file/local paths pass through.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

_HTTP_SCHEMES = {"http", "https"}


def authenticated_url(
    repo_url: str, token: str | None, username: str = "oauth2"
) -> str:
    """Inject ``username:token`` userinfo into an http(s) URL; else return as-is."""
    if not token:
        return repo_url
    parts = urlsplit(repo_url)
    if parts.scheme not in _HTTP_SCHEMES or not parts.hostname:
        return repo_url
    userinfo = f"{quote(username, safe='')}:{quote(token, safe='')}"
    netloc = f"{userinfo}@{parts.hostname}"
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_url(repo_url: str) -> str:
    """Strip any userinfo (token/credentials) from a URL — safe for logs/errors."""
    parts = urlsplit(repo_url)
    if not parts.hostname or (parts.username is None and parts.password is None):
        return repo_url
    netloc = parts.hostname
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
