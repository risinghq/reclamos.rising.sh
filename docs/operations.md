# Operations

## Local development

Install the pinned toolchain and dependencies:

```console
mise install
mise run install
```

Run the quality gate:

```console
mise run check
```

Start PostgreSQL, the API, and the worker:

```console
docker compose up --build
```

The API listens on port 8000 and the web app runs separately with
`bun run --cwd apps/web dev` on port 5173. The health response reports
`database.ok` and `queue.ok`; both must be true for a healthy stack.

[`.env.example`](../.env.example) lists every environment variable the API, the
worker and the tests read.

Only `reclamos cards` needs `ANTHROPIC_API_KEY`, and only on the host that
builds the cards. The deployed API needs no key. Keep the key in a gitignored
`.env` with mode 600. `DAILY_USD_CAP` bounds what every process sharing the
database spends in a Lima day, and `llm_calls` records each call
([model calls](llm.md#spend-limits)).

The database is disposable. The API applies its one application schema file on
startup and owns rqueue schema setup. There are no project migrations: when
`schema.sql` changes, recreate the database with `docker compose down -v`. The
worker waits for that queue schema for up to 30 seconds before exiting if the
API has not made it ready. The worker keeps PDFs in the `pdfs` volume; the
deployed worker keeps them in the S3 bucket.

## Checks

`mise run check` never writes files. It runs these tasks, and CI runs it:

| Task        | Runs                                                                                              |
| ----------- | ------------------------------------------------------------------------------------------------- |
| `lint`      | Ruff, oxlint with `--deny-warnings`, an oxfmt check of every supported file, Terraform and tflint |
| `typecheck` | basedpyright in strict mode, `tsc -b`                                                             |
| `test`      | pytest without the `integration` marker, vitest                                                   |
| `build`     | the `reclamos-api` and `reclamos-eval` distributions, the web bundle                              |

The `check` job of the CI workflow runs `mise run check` on every pull request.
Each area has its own tasks, such as `lint:py`, `typecheck:web` and `build:py`.
`mise tasks` lists them.

`mise run fix` applies the safe Ruff and oxlint fixes and formats Python,
Terraform, Markdown, YAML, JSON, CSS, HTML and TypeScript.

The integration tests need a PostgreSQL server with the pgvector and unaccent
extensions. `mise run test:integration` starts `pgvector/pgvector:pg18` with
Docker, or uses the server in `TEST_DATABASE_URL`, and skips when neither
exists. Tests of OCR skip without `pdftoppm` and `tesseract` (see
[corpus](corpus.md)).

The `integration` job of the CI workflow runs, when Python code changes,
`mise run test:integration` and the retrieval gate (`mise run test:gate`)
against a `pgvector/pgvector:pg18` service. The gate fails when fused recall@5
on the fixed index drops more than 2 points below the committed baseline; see
[evaluation](evaluation.md#gate).

## Web deploy

The web app is the Vercel project `web`, which deploys each push to `master`
that touches `apps/web`. The Vercel CLI is not a mise tool: since 65.x its
`@vercel/*` packages ship without npm provenance, which mise's trust policy
rejects. To link or deploy by hand, run it through Bun:

```console
cd apps/web
bun x vercel link
bun x vercel deploy --prod
```

The linked project metadata is local and ignored by Git.

The page calls the API from the visitor's browser. Set `VITE_API_URL` in the
Vercel project to the API's address, such as `https://api.reclamos.example`.
Vite reads it at build time, and the default is `http://localhost:8000`. The API
answers a browser only from an origin in `WEB_ORIGINS`, so set the Terraform
variable `web_origins` to the web app's addresses. The browser calls the API
directly, with no rewrite through Vercel, so the API sees each visitor's
address.

## Rate limit

`POST /search` and `POST /cases` share one limit per client address:
`SEARCHES_PER_MINUTE` requests a minute, 30 by default, refilled evenly. Past it
they answer 429 with `Retry-After`. Each search embeds the query on the API's
CPU, so the limit keeps one client from slowing every other visitor. No route
calls a language model, so it does not guard spend.

The count lives in the API process. With one API task it is exact, and with
several each task counts on its own. The client address is the one uvicorn
resolves: behind the load balancer, Terraform sets `FORWARDED_ALLOW_IPS` to the
VPC's range, so uvicorn reads the address the load balancer appended to
`X-Forwarded-For`. A client cannot forge it, because uvicorn skips only the
trusted addresses from the right.
