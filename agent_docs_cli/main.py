"""agent-docs CLI (Typer).

Commands only (publish, view, version history):
  login, docs list, docs create, docs publish, docs versions, docs get

The CLI talks to the api repo over HTTP only. It never imports
api, mcp, or ui code and never touches a database.

Auth is a placeholder seam only: a token from AGENT_DOCS_TOKEN
or from the local config file is sent as a Bearer token. It is
never verified here and never printed. The deployer wires real
identity/authorization.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import typer

app = typer.Typer(help="agent-docs CLI: publish, view, and version history.")
docs_app = typer.Typer(help="Document commands.")
app.add_typer(docs_app, name="docs")


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
def login(
    token: str = typer.Option(
        None, "--token", help="Token to store locally (or set AGENT_DOCS_TOKEN)."
    ),
):
    """Store a token in the local config file (0600). Never printed."""
    if token is None:
        token = typer.prompt("Token", hide_input=True)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
