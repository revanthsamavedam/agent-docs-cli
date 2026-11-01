"""CLI tests: help for every command, plus a mocked-HTTP round trip."""

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
        ["apis", "import", "--help"],
    ]:
        r = runner.invoke(app, args)
        assert r.exit_code == 0, (args, r.output)


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


def test_docs_list_with_mocked_http(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_request(method, path, **kwargs):
        assert method == "GET" and path == "/v1/documents"
        return FakeResponse(
            {"documents": [{"id": "doc_abc", "title": "Demo", "latest_version": 2}]}
        )

    monkeypatch.setattr("agent_docs_cli.main._request", fake_request)
    r = runner.invoke(app, ["docs", "list"])
    assert r.exit_code == 0, r.output
    assert "doc_abc" in r.output and "Demo" in r.output
