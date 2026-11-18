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
`database.ok`, `queue.ok` and the `commit` the image was built for; both `ok`
fields must be true for a healthy stack.

[`.env.example`](../.env.example) lists every environment variable the API, the
worker and the tests read.

Only `reclamos cards` needs a model key (`ANTHROPIC_API_KEY` or
`OPENROUTER_API_KEY`), and only on the host that builds the cards. The deployed
API needs no key. Keep the keys in a gitignored `.env` with mode 600.
`DAILY_USD_CAP` bounds what every process sharing the database spends in a Lima
day, and `llm_calls` records each call ([model calls](llm.md#spend-limits)).

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

The `check` job of the CI workflow runs `mise run check` on every push to
`master` and every pull request. Each area has its own tasks, such as `lint:py`,
`typecheck:web` and `build:py`. `mise tasks` lists them.

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

## AWS deploy

`infra/` is applied by hand. Sign the AWS CLI in with your console session.
`aws login` keeps temporary credentials for up to 12 hours, and `--remote`
prints a URL to open on a device with a browser. Terraform reads them through a
`credential_process` profile:

```ini
# ~/.aws/config
[profile reclamos-login]
region = us-east-1

[profile reclamos]
credential_process = aws configure export-credentials --profile reclamos-login --format process
region = us-east-1
```

```console
aws login --remote --profile reclamos-login
export AWS_PROFILE=reclamos
```

S3 bucket names are global, so the state bucket's name carries the account ID
and is passed to `terraform init`. Create it once, with versioning, before the
first init:

```console
BUCKET=reclamos-terraform-state-$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --bucket "$BUCKET"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
terraform -chdir=infra init -backend-config=bucket="$BUCKET"
```

The task definitions name an image tag, so the first apply creates the
repository alone, then an image is pushed with the commit as its tag:

```console
terraform -chdir=infra apply -target=aws_ecr_repository.api
docker build -f apps/api/Dockerfile -t REPOSITORY:COMMIT .
docker push REPOSITORY:COMMIT
terraform -chdir=infra apply -var api_image_tag=COMMIT
```

Both applies need `api_domain_name`, `cloudflare_zone_name` and `web_origins`,
which have no default. The repository uses none of them, so the first apply
accepts any value.

DNS is on Cloudflare. Terraform writes the certificate's validation record and
the API's CNAME to the load balancer, so the full apply needs
`CLOUDFLARE_API_TOKEN`, a token with DNS edit on the zone. Both records are DNS
only: through Cloudflare's proxy, the load balancer would see Cloudflare's
addresses, and the [rate limit](#rate-limit) would count every visitor as a few
clients.

### Pipeline

Every push to `master` that passes the `check` job and, when it ran, the
`integration` job runs the `deploy` job. A run whose commit is no longer the tip
of `master` stops there: the run for the tip deploys everything up to it. The
job deploys the API when `/health` reports a commit that is missing, is not an
ancestor of the pushed one, or is separated from it by a change to a path the
image is built from (`apps/api`, `packages/eval`, `pyproject.toml`, `uv.lock`);
otherwise it skips build, push and roll. When it deploys, it builds
`apps/api/Dockerfile`, pushes the image to ECR tagged with the commit SHA
(skipping a tag that already exists), registers new revisions of the
`reclamos-api` and `reclamos-worker` task definitions with that image and tag as
`COMMIT_SHA`, updates both services, and waits until
`https://api.reclamos.rising.sh/health` reports the commit. ECR keeps the last
ten images; each carries the ~1.7 GB embedding model.

The job assumes `aws_iam_role.github_deploy` through GitHub's OIDC provider,
which trusts only this repository's `master` branch. One `terraform apply`
creates the role and the provider. If apply reports that
`token.actions.githubusercontent.com` already exists in the account, import it
instead:

```console
terraform -chdir=infra import aws_iam_openid_connect_provider.github \
  arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com
```

Then give the workflow the role's ARN as a repository variable:

```console
gh variable set AWS_DEPLOY_ROLE_ARN \
  --body "$(terraform -chdir=infra output -raw github_deploy_role_arn)"
```

The services ignore `task_definition` on apply: the pipeline owns which revision
each service runs, so a later `terraform apply` never rolls a service back to
`api_image_tag`. The job re-registers the latest revision of each family, so
changes to the containers in `infra/ecs.tf` reach the next deploy.

To redeploy a commit without a push, run the workflow by hand:

```console
gh workflow run ci.yml --ref master
```

The run checks the commit again, then deploys the web app and — when the
deployed commit is missing, is not an ancestor of it, or differs from it on an
image path — the API too. To deploy outside the workflow, run the build, push
and service-roll commands of the `deploy` job in `.github/workflows/ci.yml`
under an AWS session with the same rights.

## Web deploy

The web app is the Cloudflare Worker `reclamos-web` on the `rising` account.
`apps/web/wrangler.jsonc` serves `apps/web/dist` as static assets on
`reclamos.rising.sh`; the worker has no script. The `deploy` job deploys it on
every run, after the API part succeeds or is skipped, because a static-assets
deploy takes seconds and is idempotent. Deploy runs go one at a time, a deploy
in progress is never cancelled, and a newer push replaces a queued deploy —
harmless, because each run decides from the deployed commit, not the push diff.

The job builds with `VITE_API_URL=https://api.reclamos.rising.sh` and runs
`wrangler deploy`. The organization secrets `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` already reach the repository; the token needs Workers
edit on the account.

Wrangler is a dev dependency of `apps/web`, so a manual deploy needs no extra
install:

```console
cd apps/web
bun run build
bun x wrangler deploy
```

The page calls the API from the visitor's browser, so `VITE_API_URL` must be set
at build time (the default is `http://localhost:8000`), and the API answers a
browser only from an origin in `WEB_ORIGINS`, the Terraform `web_origins`
variable. There is no rewrite through the Worker, so the API sees each visitor's
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
