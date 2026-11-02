"""CLI tests: help for every command, plus mocked-HTTP round trips."""

import json

from typer.testing import CliRunner

from agent_docs_cli.main import app

runner = CliRunner()


def test_help_for_every_command():
    for args in [
        ["--help"],
        ["docs", "--help"],
        ["login", "--help"],
        ["docs", "list", "--help"],
        ["docs", "create", "--help"],
        ["docs", "publish", "--help"],
        ["docs", "versions", "--help"],
        ["docs", "get", "--help"],
        ["docs", "kv", "--help"],
        ["docs", "kv", "list", "--help"],
        ["docs", "kv", "set", "--help"],
        ["apis", "--help"],
        ["apis", "register", "--help"],
        ["apis", "list", "--help"],
        ["apis", "get", "--help"],
        ["apis", "update", "--help"],
        ["apis", "remove", "--help"],
        ["apis", "import", "--help"],
        ["apis", "sync", "--help"],
    ]:
        r = runner.invoke(app, args)
        assert r.exit_code == 0, (args, r.output)


def test_no_draft_command_group():
    r = runner.invoke(app, ["docs", "draft", "--help"])
    assert r.exit_code != 0


def test_login_stores_token_without_printing_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DOCS_CONFIG", str(tmp_path / "config.json"))
    secret = "EXAMPLE_TOKEN_FOR_TESTS_ONLY"
    monkeypatch.setattr(
        "agent_docs_cli.main.fetch_jwt_token", lambda: secret
    )
    r = runner.invoke(app, ["login"])
    assert r.exit_code == 0, r.output
    assert secret not in r.output
    assert json.loads((tmp_path / "config.json").read_text())["token"] == secret


def test_login_refuses_unset_token_url(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DOCS_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("agent_docs_cli.main.TOKEN_URL", "REPLACE_ME_WITH_JWT_TOKEN_URL")
    r = runner.invoke(app, ["login"])
    assert r.exit_code != 0
    assert "TOKEN_URL" in r.output


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_docs_list_with_mocked_http(monkeypatch):
    def fake_request(method, path, **kwargs):
        assert method == "GET" and path == "/v1/documents"
        return FakeResponse(
            {"documents": [
                {"id": "doc_abc", "title": "Demo", "latest_version": 2},
                {"id": "doc_new", "title": "Empty", "latest_version": None},
            ]}
        )

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    r = runner.invoke(app, ["docs", "list"])
    assert r.exit_code == 0, r.output
    assert "doc_abc" in r.output and "latest v2" in r.output
    assert "doc_new" in r.output and "no versions yet" in r.output
    assert "draft" not in r.output


def test_docs_create_and_publish_with_mocked_http(tmp_path, monkeypatch):
    """Create posts {title, html} only; publish posts {html} only —
    no base version, no change summary, no 409 handling."""
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if method == "POST" and path == "/v1/documents":
            assert kwargs["json"] == {"title": "Demo", "html": "<html>v1</html>"}
            return FakeResponse({"id": "doc_abc", "version": {"number": 1, "sha256": "a" * 64}})
        if method == "POST" and path == "/v1/documents/doc_abc/versions":
            assert kwargs["json"] == {"html": "<html>v2</html>"}
            return FakeResponse({"version": {"number": 2, "sha256": "b" * 64}})
        raise AssertionError((method, path))

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    page = tmp_path / "page.html"
    page.write_text("<html>v1</html>")
    r = runner.invoke(app, ["docs", "create", str(page), "--title", "Demo"])
    assert r.exit_code == 0, r.output
    assert "doc_abc" in r.output and "version 1" in r.output
    page.write_text("<html>v2</html>")
    r = runner.invoke(app, ["docs", "publish", "doc_abc", str(page)])
    assert r.exit_code == 0, r.output
    assert "version 2" in r.output
    assert ("POST", "/v1/documents/doc_abc/versions", {"html": "<html>v2</html>"}) in calls


def test_docs_get_by_number_hits_numbered_html_endpoint(monkeypatch):
    """An explicit --version fetches /versions/{n}/html directly;
    the list endpoint is only used to resolve latest."""
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path))
        if path == "/v1/documents/doc_abc/versions/2/html":
            return FakeResponse(text="<html>v2</html>")
        if path == "/v1/documents/doc_abc/versions":
            return FakeResponse({"versions": [
                {"number": 1, "sha256": "a" * 64},
                {"number": 2, "sha256": "b" * 64},
            ]})
        raise AssertionError((method, path))

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    r = runner.invoke(app, ["docs", "get", "doc_abc", "--version", "2"])
    assert r.exit_code == 0 and "<html>v2</html>" in r.output
    assert calls == [("GET", "/v1/documents/doc_abc/versions/2/html")]
    r = runner.invoke(app, ["docs", "get", "doc_abc"])
    assert r.exit_code == 0 and "<html>v2</html>" in r.output
    assert calls[-2:] == [
        ("GET", "/v1/documents/doc_abc/versions"),
        ("GET", "/v1/documents/doc_abc/versions/2/html"),
    ]


def test_docs_versions_lists_numbers_not_ids(monkeypatch):
    def fake_request(method, path, **kwargs):
        assert path == "/v1/documents/doc_abc/versions"
        return FakeResponse({"versions": [
            {"number": 1, "sha256": "a" * 64, "s3_key": "docs/doc_abc/v1.html", "created_at": "2026-11-02T00:00:00"},
        ]})

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    r = runner.invoke(app, ["docs", "versions", "doc_abc"])
    assert r.exit_code == 0, r.output
    assert "v1" in r.output and "docs/doc_abc/v1.html" in r.output


def test_apis_register_list_sync_with_mocked_http(monkeypatch):
    """Registry fields are app_name/base_url; token_url nullable;
    list takes a user_id filter, never an app filter."""
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if method == "POST" and path == "/v1/apis":
            assert kwargs["json"] == {"app_name": "refdp", "base_url": "https://refdp.example.com"}
            return FakeResponse({"api": {"app_name": "refdp", "base_url": "https://refdp.example.com", "token_url": None}})
        if method == "GET" and path == "/v1/apis?user_id=alice":
            return FakeResponse({"apis": [
                {"app_name": "refdp", "base_url": "https://refdp.example.com", "token_url": None},
            ]})
        if method == "POST" and path == "/v1/apis/refdp/sync":
            assert kwargs["json"] == {}
            return FakeResponse({
                "api": {"app_name": "refdp", "base_url": "https://refdp.example.com", "token_url": None},
                "swagger_url": "https://refdp.example.com/openapi.json",
                "added_endpoints": ["/reports"],
                "removed_endpoints": ["/old"],
                "unchanged_endpoints": ["/risks"],
            })
        raise AssertionError((method, path))

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    r = runner.invoke(app, ["apis", "register", "--app-name", "refdp", "--base-url", "https://refdp.example.com"])
    assert r.exit_code == 0, r.output
    assert "refdp" in r.output and "(none)" in r.output
    r = runner.invoke(app, ["apis", "list", "--user-id", "alice"])
    assert r.exit_code == 0, r.output
    assert "refdp" in r.output
    r = runner.invoke(app, ["apis", "sync", "--app-name", "refdp"])
    assert r.exit_code == 0, r.output
    assert "added: /reports" in r.output
    assert "removed (reported, not deleted): /old" in r.output
    assert "unchanged: /risks" in r.output
