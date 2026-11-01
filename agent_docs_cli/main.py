"""agent-docs CLI (Typer).

Commands only (publish, view, version history, shared state):
  login, docs list, docs create, docs publish, docs versions, docs get,
  docs kv list|get|set|delete

The CLI talks to the api repo over HTTP only. It never imports
api, mcp, or ui code and never touches a database.

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
        typer.echo(f"{d['id']}\t{d['title']}\tlatest v{d.get('latest_version')}")


@docs_app.command("create")
def docs_create(
    file: Path = typer.Argument(..., help="Plain HTML file to publish."),
    title: str = typer.Option(..., "--title", help="Document title."),
    summary: str = typer.Option("", "--summary", help="Change summary for v1."),
):
    """Create a document from an HTML file (stores version 1)."""
    html = file.read_text(encoding="utf-8")
    data = _request(
        "POST", "/v1/documents",
        json={"title": title, "html": html, "change_summary": summary},
    ).json()
    typer.echo(f"{data['id']}  version {data['version']['number']}  {data['version']['sha256']}")


@docs_app.command("publish")
def docs_publish(
    doc_id: str = typer.Argument(...),
    file: Path = typer.Argument(..., help="Plain HTML file to publish."),
    summary: str = typer.Option("", "--summary", help="Change summary."),
    base_version: str = typer.Option(
        None, "--base-version",
        help="Base version id. Defaults to the latest version.",
    ),
):
    """Publish a new immutable version of a document."""
    html = file.read_text(encoding="utf-8")
    if base_version is None:
        versions = _request("GET", f"/v1/documents/{doc_id}/versions").json()["versions"]
        if not versions:
            typer.echo("Document has no versions.", err=True)
            raise typer.Exit(code=1)
        base_version = versions[-1]["id"]
    data = _request(
        "POST", f"/v1/documents/{doc_id}/versions",
        json={
            "html": html,
            "base_version_id": base_version,
            "change_summary": summary,
        },
    ).json()
    v = data["version"]
    typer.echo(f"{v['id']}  version {v['number']}  {v['sha256']}")


@docs_app.command("versions")
def docs_versions(doc_id: str = typer.Argument(...)):
    """List a document's versions."""
    data = _request("GET", f"/v1/documents/{doc_id}/versions").json()
    for v in data.get("versions", []):
        typer.echo(
            f"v{v['number']}\t{v['id']}\t{v['sha256']}\t{v['change_summary']}"
        )


@docs_app.command("get")
def docs_get(
    doc_id: str = typer.Argument(...),
    version: int = typer.Option(None, "--version", help="Version number; defaults to latest."),
    out: Path = typer.Option(None, "--out", help="File to write the HTML to."),
):
    """Fetch a version's raw HTML (byte-identical to what was published)."""
    versions = _request("GET", f"/v1/documents/{doc_id}/versions").json()["versions"]
    if version is None:
        chosen = versions[-1]
    else:
        matches = [v for v in versions if v["number"] == version]
        if not matches:
            typer.echo(f"No version {version}.", err=True)
            raise typer.Exit(code=1)
        chosen = matches[0]
    html = _request(
        "GET", f"/v1/documents/{doc_id}/versions/{chosen['id']}/html"
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


@apis_app.command("register")
def apis_register(
    name: str = typer.Option(..., "--name"),
    api_url: str = typer.Option(..., "--api-url"),
    token_url: str = typer.Option(..., "--token-url"),
    scope: str = typer.Option("", "--scope"),
    app: str = typer.Option(None, "--app"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Register an internal API (app short name, base URL, per-endpoint token URL, Swagger doc URL). Stores URLs only, never tokens."""
    payload = {"name": name, "api_url": api_url, "token_url": token_url, "scope": scope}
    if app:
        payload["app"] = app
    if swagger_url:
        payload["swagger_url"] = swagger_url
    data = _request("POST", "/v1/apis", json=payload).json()
    a = data["api"]
    typer.echo(f"{a['name']}\t{a['api_url']}\t{a['token_url']}")


@apis_app.command("list")
def apis_list(app: str = typer.Option(None, "--app")):
    """List registered internal APIs (optionally for one app)."""
    path = f"/v1/apis?app={app}" if app else "/v1/apis"
    for a in _request("GET", path).json().get("apis", []):
        typer.echo(f"{a['name']}\t{a['api_url']}\t{a['token_url']}")


@apis_app.command("get")
def apis_get(name: str = typer.Argument(...)):
    """Get one registered internal API."""
    a = _request("GET", f"/v1/apis/{name}").json()["api"]
    typer.echo(f"{a['name']}\t{a['api_url']}\t{a['token_url']}\t{a.get('scope', '')}")


@apis_app.command("sync")
def apis_sync(
    app: str = typer.Option(..., "--app"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Fetch the latest Swagger doc for an app and update its registry entry.

    With --swagger-url, that URL is stored in the app config; without
    it, the stored swagger_url is used, so a later sync needs no URL:
    `apis sync --app refdp`.
    """
    payload = {}
    if swagger_url:
        payload["swagger_url"] = swagger_url
    data = _request("POST", f"/v1/apis/{app}/sync", json=payload).json()
    a = data["api"]
    typer.echo(f"{a['name']}\t{a['api_url']}\t{a['token_url']}")
    typer.echo(f"swagger: {data['swagger_url']}")
    typer.echo(f"added: {', '.join(data['added_endpoints']) or '(none)'}")
    typer.echo(f"removed (reported, not deleted): {', '.join(data['removed_endpoints']) or '(none)'}")
    typer.echo(f"unchanged: {', '.join(data['unchanged_endpoints']) or '(none)'}")


@apis_app.command("update")
def apis_update(
    name: str = typer.Argument(...),
    api_url: str = typer.Option(None, "--api-url"),
    token_url: str = typer.Option(None, "--token-url"),
    scope: str = typer.Option(None, "--scope"),
    swagger_url: str = typer.Option(None, "--swagger-url"),
):
    """Update a registered API's URLs (rotating a token URL needs no document republishing)."""
    payload = {k: v for k, v in {"api_url": api_url, "token_url": token_url, "scope": scope, "swagger_url": swagger_url}.items() if v is not None}
    a = _request("PUT", f"/v1/apis/{name}", json=payload).json()["api"]
    typer.echo(f"{a['name']}\t{a['api_url']}\t{a['token_url']}")


@apis_app.command("remove")
def apis_remove(name: str = typer.Argument(...)):
    """Remove a registered internal API."""
    data = _request("DELETE", f"/v1/apis/{name}").json()
    typer.echo(f"{name} {'removed' if data.get('deleted') else 'not found'}")


@apis_app.command("import")
def apis_import(file: Path = typer.Argument(..., help="JSON file: a list of {name, api_url, token_url, scope?} objects.")):
    """Register many internal APIs from a JSON file."""
    entries = json.loads(file.read_text(encoding="utf-8"))
    for entry in entries:
        data = _request("POST", "/v1/apis", json=entry).json()
        typer.echo(f"registered {data['api']['name']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
