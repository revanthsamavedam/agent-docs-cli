"""agent-docs CLI (Typer).

Commands only (publish, view, version history, shared state,
registered APIs):
  login, docs list, docs create, docs publish, docs versions, docs get,
  docs kv list|get|set|delete,
  apis register|list|get|update|remove|import|sync

The CLI talks to the api repo over HTTP only. It never imports
api, mcp, or ui code and never touches a database.

Publishing appends the next version: the API computes
max(version_no)+1 itself, so publish sends only {html} — no base
version, no change summary, no conflict handling. Versions are
addressed by NUMBER, never by id: an unknown number is a 404
from the API, surfaced as-is, never a silent fall back to latest.

Auth: the JWT token URL is set in code below (TOKEN_URL), NOT
as a user-facing option or environment variable. The maintainer
replaces TOKEN_URL in this file before distributing the CLI;
end users just run ``login`` and never configure it, and the
fetched token is never printed. The deployer wires real
identity/authorization.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import typer

app = typer.Typer(help="agent-docs CLI: publish, view, version history, and shared state.")
docs_app = typer.Typer(help="Document commands.")
app.add_typer(docs_app, name="docs")
kv_app = typer.Typer(help="Shared document state commands.")
docs_app.add_typer(kv_app, name="kv")
apis_app = typer.Typer(help="Registered internal API commands.")
app.add_typer(apis_app, name="apis")

# JWT token URL, set in code — not a user option, not an env var.
# MAINTAINER: replace this value with the real token URL before
# distributing the CLI. End users must never be asked to set it.
# The fetch function below posts to this URL and reads the JWT
# from the response's ``access_token`` field; adjust the request
# body/fields here, in code, if your token URL's flow differs.
TOKEN_URL = "REPLACE_ME_WITH_JWT_TOKEN_URL"


def fetch_jwt_token() -> str:
    """Fetch a JWT from the code-configured TOKEN_URL."""
    if not TOKEN_URL or TOKEN_URL.startswith("REPLACE_ME"):
        typer.echo(
            "Token URL is not set in code. Replace TOKEN_URL in "
            "agent_docs_cli/main.py before distributing this CLI.",
            err=True,
        )
        raise typer.Exit(code=1)
    with httpx.Client(timeout=30, trust_env=False) as c:
        r = c.post(TOKEN_URL)
    if r.status_code >= 400:
        typer.echo(f"Token fetch failed: {r.status_code}", err=True)
        raise typer.Exit(code=1)
    token = r.json().get("access_token")
    if not token:
        typer.echo("Token URL did not return an access_token.", err=True)
        raise typer.Exit(code=1)
    return token


def api_base_url() -> str:
    return os.environ.get("AGENT_DOCS_API_URL", "http://127.0.0.1:8000").rstrip("/")


def config_path() -> Path:
    override = os.environ.get("AGENT_DOCS_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "agent-docs" / "config.json"


def load_token() -> str | None:
    token = os.environ.get("AGENT_DOCS_TOKEN")
    if token:
        return token
    path = config_path()
    if path.exists():
        try:
            return json.loads(path.read_text()).get("token")
        except Exception:
            return None
    return None


def _headers() -> dict[str, str]:
    token = load_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request(method: str, path: str, **kwargs):
    """Single HTTP seam, patchable in tests.

    trust_env=False: the API URL is configured and internal/local,
    so it must not be routed through an ambient HTTP proxy, and
    bracketed IPv6 entries in no_proxy break httpx's proxy parsing.
    An API error (>=400) is echoed and exits: a 404 for an unknown
    version number is surfaced, never a silent fall back to latest.
    """
    with httpx.Client(base_url=api_base_url(), headers=_headers(), timeout=30, trust_env=False) as c:
        r = c.request(method, path, **kwargs)
        if r.status_code >= 400:
            typer.echo(f"Error {r.status_code}: {r.text}", err=True)
            raise typer.Exit(code=1)
        return r


@app.command()
def login():
    """Fetch a JWT from the code-configured TOKEN_URL and store it locally (0600). Never printed. Takes no arguments — users never configure the URL."""
    token = fetch_jwt_token()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token}))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    typer.echo(f"Saved token to {path}")


@docs_app.command("list")
def docs_list():
    """List documents."""
    data = _request("GET", "/v1/documents").json()
    for d in data.get("documents", []):
        latest = d.get("latest_version")
        status = f"latest v{latest}" if latest is not None else "no versions yet"
        typer.echo(f"{d['id']}\t{d['title']}\t{status}")


@docs_app.command("create")
def docs_create(
    file: Path = typer.Argument(..., help="Plain HTML file to publish."),
    title: str = typer.Option(..., "--title", help="Document title."),
):
    """Create a document from an HTML file (stores version 1)."""
    html = file.read_text(encoding="utf-8")
    data = _request(
        "POST", "/v1/documents",
        json={"title": title, "html": html},
    ).json()
    typer.echo(f"{data['id']}  version {data['version']['number']}  {data['version']['sha256']}")


@docs_app.command("publish")
def docs_publish(
    doc_id: str = typer.Argument(...),
    file: Path = typer.Argument(..., help="Plain HTML file to publish."),
):
    """Publish a new immutable version of a document.

    The API appends the next version number itself; this command
    sends only the HTML.
    """
    html = file.read_text(encoding="utf-8")
    data = _request(
        "POST", f"/v1/documents/{doc_id}/versions",
        json={"html": html},
    ).json()
    v = data["version"]
    typer.echo(f"version {v['number']}  {v['sha256']}")


@docs_app.command("versions")
def docs_versions(doc_id: str = typer.Argument(...)):
    """List a document's versions."""
    data = _request("GET", f"/v1/documents/{doc_id}/versions").json()
    for v in data.get("versions", []):
        typer.echo(
            f"v{v['number']}\t{v['sha256']}\t{v.get('s3_key', '')}\t{v.get('created_at', '')}"
        )


@docs_app.command("get")
def docs_get(
    doc_id: str = typer.Argument(...),
    version: int = typer.Option(None, "--version", help="Version number; defaults to latest."),
    out: Path = typer.Option(None, "--out", help="File to write the HTML to."),
):
    """Fetch a version's raw HTML (byte-identical to what was published).

    An explicit --version is fetched directly: an unknown number
    is a 404 from the API, surfaced as-is, never a fall back to
    latest. Without --version, the highest listed version number
    is fetched.
    """
    if version is not None:
        html = _request(
            "GET", f"/v1/documents/{doc_id}/versions/{version}/html"
        ).text
    else:
        versions = _request("GET", f"/v1/documents/{doc_id}/versions").json()["versions"]
        if not versions:
            typer.echo("Document has no versions.", err=True)
            raise typer.Exit(code=1)
        latest = max(v["number"] for v in versions)
        html = _request(
            "GET", f"/v1/documents/{doc_id}/versions/{latest}/html"
        ).text
    if out is not None:
        out.write_text(html, encoding="utf-8")
        typer.echo(f"Wrote {out}")
    else:
        typer.echo(html)


@kv_app.command("list")
def kv_list(doc_id: str = typer.Argument(...)):
    """List a document's shared state (all keys)."""
    data = _request("GET", f"/v1/documents/{doc_id}/state").json()
    for k, v in (data.get("state") or {}).items():
        typer.echo(f"{k}\t{json.dumps(v)}")


@kv_app.command("get")
def kv_get(doc_id: str = typer.Argument(...), key: str = typer.Argument(...)):
    """Get one shared-state key's value."""
    data = _request("GET", f"/v1/documents/{doc_id}/state/{key}").json()
    typer.echo(json.dumps(data.get("value")))


@kv_app.command("set")
def kv_set(doc_id: str = typer.Argument(...), key: str = typer.Argument(...), value: str = typer.Argument(...)):
    """Set one shared-state key. Value is parsed as JSON if possible, else kept as a string."""
    try:
        parsed = json.loads(value)
    except Exception:
        parsed = value
    data = _request("PUT", f"/v1/documents/{doc_id}/state/{key}", json={"value": parsed}).json()
    typer.echo(f"{key} {'deleted' if data.get('deleted') else 'set'}")


@kv_app.command("delete")
def kv_delete(doc_id: str = typer.Argument(...), key: str = typer.Argument(...)):
    """Delete one shared-state key."""
    data = _request("DELETE", f"/v1/documents/{doc_id}/state/{key}").json()
    typer.echo(f"{key} {'deleted' if data.get('deleted') else 'not found'}")


def _api_line(a: dict) -> str:
    return f"{a['app_name']}\t{a['base_url']}\t{a.get('token_url') or '(none)'}"


@apis_app.command("register")
def apis_register(
    app_name: str = typer.Option(..., "--app-name"),
    base_url: str = typer.Option(..., "--base-url"),
    token_url: str = typer.Option(None, "--token-url"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Register an internal API (app short name, base URL, optional per-endpoint token URL, optional Swagger doc URL). Stores URLs only, never tokens. A missing token URL means no token fetch (apiKey/bearer schemes)."""
    payload = {"app_name": app_name, "base_url": base_url}
    if token_url is not None:
        payload["token_url"] = token_url
    if swagger_url is not None:
        payload["swagger_url"] = swagger_url
    data = _request("POST", "/v1/apis", json=payload).json()
    typer.echo(_api_line(data["api"]))


@apis_app.command("list")
def apis_list(user_id: str = typer.Option(None, "--user-id")):
    """List registered internal APIs, optionally filtered by registering user id (audit lookup only, never access control)."""
    path = f"/v1/apis?user_id={user_id}" if user_id else "/v1/apis"
    for a in _request("GET", path).json().get("apis", []):
        typer.echo(_api_line(a))


@apis_app.command("get")
def apis_get(app_name: str = typer.Argument(...)):
    """Get one registered internal API."""
    a = _request("GET", f"/v1/apis/{app_name}").json()["api"]
    typer.echo(f"{a['app_name']}\t{a['base_url']}\t{a.get('token_url') or '(none)'}\t{a.get('swagger_url') or ''}")


@apis_app.command("sync")
def apis_sync(
    app_name: str = typer.Option(..., "--app-name"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Fetch the latest Swagger doc for an app and update its registry entry.

    With --swagger-url, that URL is stored in the app config; without
    it, the stored swagger_url is used, so a later sync needs no URL:
    `apis sync --app-name refdp`. Base URL comes from servers[0].url,
    token URL from the Swagger oauth2 tokenUrl if present, else the
    existing token URL is kept. Removed endpoints are reported,
    never auto-deleted.
    """
    payload = {}
    if swagger_url:
        payload["swagger_url"] = swagger_url
    data = _request("POST", f"/v1/apis/{app_name}/sync", json=payload).json()
    typer.echo(_api_line(data["api"]))
    typer.echo(f"swagger: {data['swagger_url']}")
    typer.echo(f"added: {', '.join(data['added_endpoints']) or '(none)'}")
    typer.echo(f"removed (reported, not deleted): {', '.join(data['removed_endpoints']) or '(none)'}")
    typer.echo(f"unchanged: {', '.join(data['unchanged_endpoints']) or '(none)'}")


@apis_app.command("update")
def apis_update(
    app_name: str = typer.Argument(...),
    base_url: str = typer.Option(None, "--base-url"),
    token_url: str = typer.Option(None, "--token-url"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Update a registered API's URLs (rotating a token URL needs no document republishing). Only options given are sent; omitted fields are kept."""
    payload = {k: v for k, v in {"base_url": base_url, "token_url": token_url, "swagger_url": swagger_url}.items() if v is not None}
    a = _request("PUT", f"/v1/apis/{app_name}", json=payload).json()["api"]
    typer.echo(_api_line(a))


@apis_app.command("remove")
def apis_remove(app_name: str = typer.Argument(...)):
    """Remove a registered internal API."""
    data = _request("DELETE", f"/v1/apis/{app_name}").json()
    typer.echo(f"{app_name} {'removed' if data.get('deleted') else 'not found'}")


@apis_app.command("import")
def apis_import(file: Path = typer.Argument(..., help="JSON file: a list of {app_name, base_url, token_url?, swagger_url?} objects.")):
    """Register many internal APIs from a JSON file."""
    entries = json.loads(file.read_text(encoding="utf-8"))
    for entry in entries:
        data = _request("POST", "/v1/apis", json=entry).json()
        typer.echo(f"registered {data['api']['app_name']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
