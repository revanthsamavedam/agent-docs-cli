# Canvas CLI — Copilot instructions (repo: canvas-cli)

You are building the Canvas CLI from scratch. Canvas is a governed
publication and audit layer for agent-built documents. This repo
is the CLI only. Do not build the API, viewer, or MCP server here
— those are separate repos. This repo is a thin client over the
Canvas API: it adds no endpoints, no storage, and no business
logic of its own.

## Authentication: unauthenticated for now

- **Every API call this CLI makes is unauthenticated for now.**
  Do not build login, token storage, token refresh, session
  handling, or RBAC. The maintainer will wire authentication later
  and will say so explicitly when that changes.
- Send no credentials with any request. Do not read a token from
  the environment and attach it, and do not perform a token fetch,
  even if the API registry contains a `token_url`.
- Never print a secret, token, or credential, and never store one
  in a config file, a history file, or a test fixture.

## Stack and configuration

- Python, Typer-style CLI (or the equivalent the maintainer
  already uses — keep one CLI framework, not two).
- API base URL from `CANVAS_API_URL` (default
  `http://127.0.0.1:8000`). Do not hardcode a production URL.
  The previous agent-docs CLI used `AGENT_DOCS_API_URL`; in
  Canvas, the variable is `CANVAS_API_URL`.
- HTTP client with a sane timeout (30s). Errors from the API are
  surfaced as-is (status + detail), never rewritten into a
  different meaning.
- Tests: pytest, with the HTTP client mocked. Never hit a live
  API from a unit test.

## Commands (build exactly these)

Documents:
- `docs create --title <title> --html-file <file>` — creates the
  document AND version 1 in one call (`POST /v1/documents`
  with `{title, html}`).
- `docs list` — `GET /v1/documents`.
- `docs get <doc_id> [--version N]` — latest by default; `--version
  N` pins exactly N. A missing version is an API 404, never a
  silent fallback to latest. Never accept a version id.
- `docs publish <doc_id> --html-file <file>` — publishes a new
  version (`POST /v1/documents/{doc_id}/versions` with `{html}`
  only). No base-version argument, no change-summary argument,
  no draft argument.
- `docs versions <doc_id>` — `GET /v1/documents/{doc_id}/versions`.

Shared state (document-scoped, not version-scoped):
- `state get <doc_id>` — all keys.
- `state get <doc_id> <key>` — one key (API 404 if absent).
- `state set <doc_id> <key> <json-value>` — PUT one key.
- `state patch <doc_id> <json-patch>` — POST a patch object.
- `state delete <doc_id> <key>` — DELETE one key.
- Setting a key to null deletes it. Changing state never creates
  a version.

Registry:
- `apis register <app_name> --base-url <url>
  [--token-url <url>] [--swagger-url <url>]` — fields are
  `app_name` / `base_url`, nullable `token_url` / `swagger_url`.
  No `scope` field, no `name` / `api_url` fields.
- `apis list`, `apis get <app_name>`,
  `apis update <app_name> [--base-url ...] [--token-url ...]
  [--swagger-url ...]`, `apis delete <app_name>`,
  `apis sync <app_name>` — sync is owner-triggered, from the
  app's Swagger spec; removed endpoints are reported, never
  auto-deleted (the API does this; the CLI only surfaces it).
- `apis import <file>` — JSON list of
  `{app_name, base_url, token_url?, swagger_url?}` objects.
- API names are slugs: `^[a-z0-9][a-z0-9_\-]{0,63}$`. URLs must
  be https (http only for localhost dev). Validate these in the
  CLI and surface the API's error unchanged if it rejects them.

## Rules this CLI must not break

- Versions are addressed by NUMBER only. There are no version
  ids, no `base_version_id`, no 409 flow, no `change_summary`,
  no `byte_size`.
- No drafts: no draft create, no draft save, no draft publish,
  no `?draft=1`.
- Publish posts `{html}` only. Create posts `{title, html}` only.
- State changes never create a version, and a publish never
  resets state.
- The CLI must not add endpoints, auth, comments, approvals,
  grants, or sharing. If the API does not have an operation, the
  CLI does not invent one.
- Output: machine-readable where it matters (tab-separated or
  JSON for list/get), human-readable errors otherwise. A list
  filter by user is a record lookup, never access control — in
  unauthenticated mode there is no user filter at all.

## Tests and acceptance

- Tests for: create (version 1), publish (next version, no
  base-version arg), get latest vs pinned version (404, no
  fallback), state set/patch/delete (null = delete), registry
  field names (`app_name`/`base_url`, nullable token/swagger
  URLs), and error passthrough.
- Acceptance, before calling the build done: against a running
  Canvas API, create a document, publish v2, fetch v1 and v2
  (both unchanged and correct), fetch a missing version (404),
  and set a state key (no new version created).

## Never reintroduce

Drafts, approvals, version ids, `base_version_id`, 409 flow,
`change_summary`, `byte_size`, `name`/`api_url`/`scope` registry
fields, comments, notifications, grants, authentication, login,
token verification, or any local storage of documents, versions,
or state.
