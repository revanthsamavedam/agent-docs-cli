# agent-docs-cli

Python (Typer) CLI for agent-docs. Separate repo — it talks to
the api repo over HTTP and never imports api, mcp, or ui code,
and never touches a database.

## Scope — publish, view, and version history only

- `login` — fetch a JWT from the code-configured TOKEN_URL and
  store it locally (0600 config file, never printed). Takes no
  arguments: end users never configure the token URL.
- `docs list` — latest version number per document, or
  "no versions yet" for a document with none.
- `docs create <file.html> --title <title>` — creates the
  document and stores version 1 in one call.
- `docs publish <id> <file.html>` — publishes a new immutable
  version. The API appends the next version number itself, so
  this command sends only the HTML: no base version, no change
  summary, no conflict handling.
- `docs versions <id>`
- `docs get <id> [--version <n>] [--out <file>]` — versions are
  addressed by NUMBER. An explicit `--version` fetches that
  version directly; an unknown number is a 404 from the API,
  surfaced as-is, never a silent fall back to latest. Without
  `--version`, the highest listed version number is fetched.
- `docs kv list <id>` / `docs kv get <id> <key>` /
  `docs kv set <id> <key> <value>` / `docs kv delete <id> <key>`
  — shared document state (document-scoped, never creates a version)
- `apis register --app-name <name> --base-url <url> [--token-url <url>] [--swagger-url <url>]`
  / `apis list [--user-id <user>]` / `apis get <name>` /
  `apis update <name> [--base-url <url>] [--token-url <url>] [--swagger-url <url>]`
  / `apis remove <name>` / `apis import <file.json>`
  / `apis sync --app-name <name> [--swagger-url <url>]`
  — register internal APIs once for documents to use at view time;
  stores URLs only, never tokens. A missing token URL means no
  token fetch (apiKey/bearer schemes) and is valid. The list
  filter is by registering user id only — an audit lookup, never
  access control. `sync` fetches the latest Swagger doc for an
  app and updates its registry entry; with `--swagger-url` that
  URL is stored in the app config, without it the stored URL is
  used, so later syncs need no URL. Base URL comes from
  servers[0].url, token URL from the Swagger oauth2 tokenUrl if
  present, else the existing token URL is kept. Removed
  endpoints are reported, never auto-deleted.

No comment, state, grant, or approval commands. Documents are
plain HTML files; the CLI never writes React/JSX into them.

## Configuration — code, not user options

- `TOKEN_URL` in `agent_docs_cli/main.py` — the JWT token URL.
  MAINTAINER ONLY: replace this constant in code before
  distributing the CLI. It is deliberately not a CLI option or
  an end-user environment variable.
- `AGENT_DOCS_API_URL` — api repo base URL.
  Default: `http://127.0.0.1:8000`
- `AGENT_DOCS_TOKEN` — token sent as a Bearer token (overrides the
  config file). Dev/test override only; it is never verified here
  and never printed. The deployer wires real identity.
- `AGENT_DOCS_CONFIG` — config file path override (tests use this).
  Default: `~/.config/agent-docs/config.json`

## Run

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m agent_docs_cli --help
.venv/bin/python -m agent_docs_cli docs list
```

With the api repo running on `http://127.0.0.1:8000`:

```
.venv/bin/python -m agent_docs_cli docs create report.html --title "Q3 report"
.venv/bin/python -m agent_docs_cli docs publish <id> report-v2.html
.venv/bin/python -m agent_docs_cli docs versions <id>
.venv/bin/python -m agent_docs_cli docs get <id> --version 1 --out report-v1.html
```

## Tests

```
.venv/bin/python -m pytest -q
```
