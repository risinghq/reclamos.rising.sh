# Outcomes

`reclamos outcomes load` loads how OSIPTEL's tribunal decided every appeal and
complaint file since 2017. `POST /cases` attaches those counts to each case
whose file it finds. No step calls a model. The code is in
`apps/api/src/reclamos_api/outcomes/`.

| File            | Owns                                                          |
| --------------- | ------------------------------------------------------------- |
| `source.py`     | Reading the PUNKU workbooks and the file numbers              |
| `labels.py`     | The concept table, the outcome names and each company's brand |
| `repository.py` | The outcome tables, the load and the precomputed counts       |
| `commands.py`   | `reclamos outcomes load` and its corpus match                 |
| `serve.py`      | The lookup `POST /cases` runs                                 |

## Load

```sh
uv run reclamos outcomes load
uv run reclamos outcomes load --zip Datasets-PUNKU-OSIPTEL.zip
```

Without `--zip` the command downloads the zip that `SOURCE_URL` in `source.py`
names, 188 MB, to a temporary directory. The load of the 2026-07-24 cut takes
under two minutes. It prints these counts from inside its transaction, so they
describe the tables it wrote:

```text
source: https://punku.osiptel.gob.pe/Archivos/Datasets-PUNKU-OSIPTEL.zip, cut 2026-07-24
decisions: 1,012,182 rows, 1,012,179 files
subjects: 1,298,725 file concepts, 1,217 counts
concept labels not in the table: 0
decisions by year:
  2017 112,960
  ...
decisions by sentido:
  IMPROCEDENTE 331,012
  ...
corpus: 113 of 144 expedientes numbered 2016 or later match a file
  ...
```

The load replaces four tables in one transaction:

| Table               | One row per                                                                     |
| ------------------- | ------------------------------------------------------------------------------- |
| `outcome_source`    | load: the source URL, the cut date and the load time                            |
| `outcome_decisions` | decision: file number, year and type, date, sentido, outcome, company and brand |
| `outcome_subjects`  | file and concept, with its detail                                               |
| `outcome_stats`     | file type, concept, detail and brand, with the counts by outcome                |

## Source

PUNKU, OSIPTEL's open data portal, publishes one zip. Its folder
`11. RECLAMOS DE USUARIOS - SEGUNDA INSTANCIA` holds two workbooks the load
reads:

- `11.2. EXPEDIENTES RESUELTOS`: one row per decision, with `Nro Expediente`,
  `Recurso/Tipo de expediente` (`RA` appeal, `RQJ` complaint),
  `Fecha Expedición`, `Sentido` and `Empresa`.
- `11.4. EXPEDIENTES RESUELTOS POR MATERIA Y SERVICIO`: one row per file,
  service and subject, with `Concepto` and `Subconcepto`.

Each workbook splits its rows into sheets by period. A sheet may start with a
title and may have an empty first column, so the reader finds the header row by
its column names. A sheet without that header is a note. The cut date comes from
the note that reads `Fecha de corte de la información`. The command exits with
an error when a workbook is missing, holds no rows, has a file number it cannot
read, or states no cut date.

## Counting

The two workbooks join on the file number, year and type. A file counts once,
under its latest decision. Four sentidos are outcomes: `FUNDADO`,
`PARCIALMENTE FUNDADO` (`fundado_en_parte`), `INFUNDADO` and `IMPROCEDENTE`.
Every other sentido counts as `other`: `DAR POR CONCLUIDO`, `ARCHIVAR`,
`DEJAR SIN EFECTO LA ELEVACION`, `ANULADO`, `ACUMULAR`, `NULIDAD` and
`RECHAZAR`.

A file with several concepts counts once in each. A file with several services
under one concept counts once there. `outcome_stats` holds one row for each file
type, concept and detail, and one with an empty detail for the concept as a
whole. It also holds a row for each brand with at least 100 files in it.
`first_year` and `last_year` are the years of the decisions counted.

## Concepts

The `Concepto` labels change in 2023: `FACTURACIÓN` becomes
`FACTURACIÓN Y COBRO`, `CALIDAD` becomes
`CALIDAD E IDONEIDAD EN LA PRESTACIÓN DEL SERVICIO`, `INFRACCIÓN DE PLAZOS` and
`NO CONTESTACIÓN OPORTUNA` become `FALTA DE RESPUESTA AL RECLAMO`. Some older
labels still appear in later years.

`CONCEPTS` in `labels.py` maps each of the 74 labels of the 2026-07-24 cut to
one of 31 concepts. A label is compared without case, accents or repeated
spaces. A label missing from the table stays its own concept, its text in lower
case, and the load prints it under `concept labels not in the table`.

`Subconcepto` is the concept's detail, such as `CARGO FIJO` or
`CARGO/ACUSE INVÁLIDO`, compared the same way. `NO APLICA` means no detail. The
detail is shown in its most common spelling, in lower case, with the
abbreviation `EO` written out as `empresa operadora`.

## Match

`file_key` in `source.py` reads a number, a year and a type from an expediente:
`0032112-2019/TRASU/ST-RA` is file 32112 of 2019, type `RA`. It accepts spaces
around the hyphen and `STRQJ` for `ST-RQJ`. An expediente of the older `GUS-RA`
form gives no key. Appeals and complaints are numbered apart, so the type is
part of the key.

The load ends by matching the corpus. For each expediente numbered 2016 or later
that names no file of its type in `11.2`, it prints the reason: the resolution
came before the first decision in `11.2` or after the last one, `11.2` holds the
number only as the other type, or it holds no file with that number.

## Serving

`statistics` in `serve.py` takes the expedientes of the cases `POST /cases`
returns. For each one whose file is in `outcome_decisions`, it reads the file's
concepts from `outcome_subjects`. For each concept it serves the row of the
file's detail when that row holds at least 100 files, and the concept's row
otherwise. It adds the row of the brand of the file's company when there is one.
One statement reads the counts and the source, so both come from one load. A
case whose file is not in `11.2`, or has no concept in `11.4`, gets no
statistics, and so does every case before the first load.
[Cases](cases.md#route) shows the field.

The web app writes each concept as one Spanish sentence, explains each outcome
in one line, and names the source and its cut date.
`apps/web/src/Statistics.tsx` holds that text.

## Tests

`test_outcomes.py` writes a fixture zip with `tests/punku.py`. Its sheets use
both layouts, and its labels come from before and after 2023. The tests read it,
check `file_key` on each expediente form, and run `reclamos outcomes load` on
the fixture index. They then check `POST /cases` for cases with and without a
matching file, including the brand row at 100 files and the fallback from the
detail to the concept. A last test reloads the tables during a lookup and checks
that the cut date and the counts it serves come from one load.
