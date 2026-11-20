# Corpus

The corpus is the set of user-complaint resolutions that answers are drawn from.
Each resolution has a sector: `telecom` for OSIPTEL TRASU resolutions (the
Tribunal Administrativo de Solución de Reclamos de Usuarios) and `energy` for
Osinergmin JARU resolutions (the Junta de Apelaciones de Reclamos de Usuarios,
which resolves electricity and natural-gas complaints). The code is in
`apps/api/src/reclamos_api/corpus/` and the command line is `reclamos`.

## Sources

Each source is declared in `corpus/sources.py` with its slug, sector, regulator,
tribunal, collection URL, the function that reads the listing title, and the
filter that decides which entries the corpus keeps.

OSIPTEL publishes the resolutions in the "Jurisprudencia" collection on gob.pe:
<https://www.gob.pe/institucion/osiptel/colecciones/52616-jurisprudencia>. Each
entry is titled `Expediente N.° NNNNNNN-YYYY/TRASU/ST-RA` (an appeal) or
`ST-RQJ` (a complaint about the procedure), and links to a page that links the
PDF on `cdn.www.gob.pe`. Some older titles repeat the label, as in
`Expediente N.° Expediente 005687-2009/...`. The crawler stores the bare number,
`NNNNNNN-YYYY/TRASU/ST-RA`, in `resolutions.expediente`.

Osinergmin publishes JARU resolutions mixed with other tribunals in
<https://www.gob.pe/institucion/osinergmin/colecciones/837>. JARU titles carry
`OS/JARU-` in their number (`...-OS/JARU-S2` for a Sala Unipersonal, for
example). Entries of the Cuerpos Colegiados (`OS/CC-`) and the Tribunal de
Solución de Controversias (`OS/TSC-`) decide disputes between companies, not
user complaints, so they are recorded with `skipped_reason` set to
`cuerpo_colegiado` or `tribunal_controversias`. Any other entry without a JARU
number is recorded as `not_jaru`. Skipped rows stay in the table for the
statistics and never move to `corpus.download`.

The crawler follows the robots rules of each host. gob.pe disallows `?sheet=`
pagination, so the crawler never pages, but `filter[per_page]` accepts sizes
above 100. It asks the collection for one publication-date window at a time with
`filter[start_date]`, `filter[end_date]` and `filter[per_page]=100`. When a
window reports more entries than it shows, it is split in two until it fits. A
single day cannot be split, so it is asked for again with `filter[per_page]` set
to its entry count. Only when that answer still shows fewer entries than the
count is the day recorded in `listing_failures` with the reason
`listing_truncated` under the collection's source slug, and `corpus stats` lists
it.

Requests are one per second per process, and each says who asks:

```text
reclamos-corpus/0.1 (+https://github.com/risinghq/reclamos.rising.sh)
```

Redirects are followed by hand, up to 5. Each hop is checked against the
robots.txt of its own host and waits its own second. A chain longer than 5 fails
with `too_many_redirects`. Each host's robots.txt is cached for an hour, or for
five minutes when the host could not answer (5xx, 429 or unreachable), so a
transient failure is retried and fails the request as `robots_unreachable`. When
an Allow and a Disallow rule match equally, Allow wins. A `Crawl-delay` that is
not a plain number is ignored.

## Pipeline

Each step is an `rqueue` job, and each job queues the next:

1. `corpus.discover` lists a window for each declared source and records each
   entry. Entries the source filters out get `skipped_reason` and no later stage
   runs on them.
2. `corpus.download` reads the resolution page, then stores the PDF under
   `resolutions/<id>.pdf` with its SHA-256 and size.
3. `corpus.extract` reads the text layer of each page and runs OCR on pages that
   have none. Resolutions published as scans are the common case.
4. `corpus.redact` replaces what identifies a person in `body` — names, document
   numbers, lines, emails, home addresses and account codes — with fixed labels
   (`[NOMBRE]`, `[DNI]`, `[TELÉFONO]`, `[CORREO]`, `[DIRECCIÓN]`, `[CÓDIGO]`)
   and stores the result in `redacted_body`. Names that are public record stay:
   the vocales and secretaries who sign, OSIPTEL officials in their role, the
   operators' names and institutional addresses. `body` keeps the extracted
   text; every reader after this step, passages included, sees the redacted
   text. `redactor_version` in `corpus/redact.py` marks which redactor wrote the
   text; a version that differs from the stored one makes the step run again.
5. `corpus.chunk` splits the redacted text into passages and `corpus.embed`
   stores a vector for each. [Retrieval](retrieval.md) describes both.
6. `corpus.parse` reads the number, date, operator, claim type and outcome from
   the text and the page summary. It runs last because it only fills the fields
   that filter a search: a resolution whose header the scan damaged is still
   searchable.

The `resolutions` row in `schema.sql` records which steps are finished. A job
checks its step first, so a re-run does nothing for finished work.

A step that cannot finish writes `failure_stage`, `failure_reason` and
`failure_detail` on the row, and the row stays in the table. A re-run tries
failed rows again, and parsing again needs no network, so a better parser can be
applied to stored text by running `reclamos corpus crawl`.

`parser_version` in `corpus/parse.py` marks which parser wrote the stored
fields, like `redactor_version` marks the redactor. A change to the parser bumps
it: the next `reclamos corpus crawl` then re-parses every extracted row,
including ones the older parser already stored fields for. That is how a parser
fix reaches rows that never failed — for example an energy row stored with the
wrong `appeal_kind` — without a new download or a second crawl.

The jobs run in whichever process claims them: the worker
(`python -m reclamos_api.worker`) or `reclamos corpus crawl`. Only a crawl
starts the retry of a failure. [Architecture](architecture.md#corpus-state)
lists the states of a resolution, of a listing window and of a job, who changes
each, and who clears a failure.

### What parsing reads

| Field        | Values                                                                                                                                                                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sector`     | `telecom` (OSIPTEL), `energy` (Osinergmin)                                                                                                                                                                                                                    |
| `number`     | Telecom: `NNNNNNN-YYYY-TRASU/OSIPTEL`. Energy: `NNNNN-YYYY-OS/JARU-Sn`                                                                                                                                                                                        |
| `operator`   | One of the known operators in `parse.py`, else the name as printed                                                                                                                                                                                            |
| `claim_type` | Telecom: `unrequested_contract`, `porting`, `service_cut`, `service_quality`, `billing`, `equipment`, `contract_terms`, `procedural`. Energy: `meter`, `recupero`, `connection`, `service_cut`, `service_quality`, `billing`, `consumption`, `contract_terms` |
| `outcome`    | `fundado`, `infundado`, `improcedente`, `fundado_en_parte`, `mixto`, `sin_efecto`                                                                                                                                                                             |

Telefónica del Perú S.A.A. was renamed Integratel Perú S.A.A. in 2025. They are
kept as separate operators because the resolutions print each name. Enel
Distribución Perú S.A.A. became Pluz Energía Perú S.A.A. for the same reason.

Energy parsing reads a JARU header, whose layout differs from TRASU: the
resolution number follows `OS/JARU-`, the operator sits on an
`Empresa distribuidora:` (or `Empresa:`) line, and the claim sits on `Materia:`.
A JARU resolution often rules claim by claim in its resolutive section, so
`mixto` is common; a `NULO`/`NULA`/`NULIDAD` verdict maps to `sin_efecto`.

Not every JARU file is an appeal. A `queja` complains about the procedure
itself, so it reads the kind from the `Materia:` line or the page summary, and a
queja gets the claim type `procedural`. A resolution that rules only on the
procedure — `ACUMULAR`, `SUSPENDER`, `RECTIFICAR`, `CARECE DE OBJETO`,
`DESESTIMAR` — is read as a procedural ruling: its disposition maps to
`improcedente` or `sin_efecto` and its claim type is `procedural`.

Newer JARU formats print no `Empresa` line and call the company "la empresa
distribuidora" throughout. For those, the operator comes from the party named
after `contra`, or from the `Resolución impugnada` code — `GNLC-RES-*` is the
first-instance resolution series of Gas Natural de Lima y Callao S.A., and the
other prefixes in `IMPUGNADA_OPERATORS` work the same way. Only prefixes that
the labeled rows confirm are mapped, and only the `impugnada` label itself
counts — a code quoted for another case in the text or footnotes cannot name the
operator. A queja with no labeled code names no operator and stays missing.

The scan can damage any label, so two fields have a second source. The
`Empresa:` line on the resolution page, when present, names the operator. The
page summary gives the outcome when the scan lost the outcome label. A
resolution that rules differently on several claims is `mixto` even when the
summary names one ruling. An operator name that is neither a known operator nor
ends in a legal form (`S.A.`, `S.A.C.`, ...) is a misread box, so it is not
stored.

When a field is missing, the row fails at `parse` with the reason
`no_<first missing field>` and the full list in `failure_detail`.

## Commands

Run these from `apps/api` with PostgreSQL available (see
[operations](operations.md)):

```console
uv run reclamos corpus crawl
uv run reclamos corpus stats
```

`crawl` lists every publication date from 2003-01-01 (`--since`) to today
(`--until`), runs the jobs in this process until the queue is empty, then prints
the same statistics as `stats`. `stats` prints, per sector, the resolutions
found, the entries skipped by reason, the resolutions downloaded, extracted,
redacted (with the count of each label it placed), parsed, chunked and embedded,
the failures by stage and reason, and the counts of claim types and outcomes.
`reclamos corpus reindex` rebuilds the search index; see
[Retrieval](retrieval.md#re-indexing).

## Dataset export

`reclamos dataset export DIR` writes the corpus as JSONL files for publication.
Every text field is the redacted text at the current redactor version. It writes
no PDFs, no embeddings and no cards. The command refuses to write when a
resolution that has a body, or a rule document, has no redacted text at the
current version; run `reclamos corpus crawl` and `reclamos rules sync` first.

- `resolutions.jsonl`: one row per resolution — `id`, `sector`, `page_url`,
  `expediente`, `published_on`, `summary`, `pdf_url`, `pdf_sha256`, `pdf_bytes`,
  `page_count`, `ocr_pages`, `text_method`, the parsed fields (`number`,
  `resolved_on`, `operator`, `subject`, `claim_type`, `appeal_kind`, `outcome`,
  `is_precedent`) and `text`, the redacted body.
- `passages.jsonl`: one row per chunk — `resolution_id`, `ordinal`, `section`,
  `page_start`, `page_end`, `char_start`, `char_end` (offsets into the redacted
  text) and `text`.
- `rule_documents.jsonl`: one row per rule document — `slug`, `title`, `kind`,
  `approved_by`, `text_date`, `pdf_url`, `pdf_sha256`, `visitor_searchable` and
  `text`, the redacted body.
- `rule_passages.jsonl`: one row per rule passage — `document_slug`, `ordinal`,
  `label`, `text_source`, `text_date`, `pdf_url` and `text`.

## Configuration

| Variable          | Default           | Meaning                               |
| ----------------- | ----------------- | ------------------------------------- |
| `DATABASE_URL`    | built from `DB_*` | PostgreSQL connection string          |
| `PDF_STORE`       | `local`           | `local` or `s3`                       |
| `PDF_STORE_PATH`  | `.data/pdfs`      | Directory for the `local` store       |
| `PDF_BUCKET`      |                   | Bucket for the `s3` store             |
| `S3_ENDPOINT_URL` |                   | Endpoint for an S3-compatible service |

The `s3` store uses the standard AWS credential chain. The worker started by
`python -m reclamos_api.worker` runs the same jobs, so a deployed worker can
continue a crawl that `reclamos corpus crawl` began. The one-request-per-second
limit is per process: do not run both at once.

The deployed worker runs no task by default, because the corpus changes only
during a crawl. Apply Terraform with `-var worker_count=1` to run it, and with
the default again when the queue is empty.

## OCR

OCR needs `pdftoppm` from poppler-utils and `tesseract` with the Spanish
language data. On Debian:

```console
sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-spa
```

The Docker image installs them. Extraction fails a scan with the reason
`tool_missing` when they are absent, and the tests that need them skip.

## Tests

The tests replay recorded gob.pe pages and PDFs from `apps/api/tests/fixtures`
and make no network request. The corpus tests need PostgreSQL: set
`TEST_DATABASE_URL` to a server, or run Docker so the tests start
`pgvector/pgvector:pg18`. Each test creates and drops its own database.
