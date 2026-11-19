# Rules

Run the rules indexer after configuring the database and PDF store:

```console
reclamos rules sync
```

It downloads the fixed OSIPTEL PDFs, stores them through the corpus PDF store,
extracts their text, consolidates the current text, and embeds the passages with
the configured local embedding model. It makes no language-model call. A second
run leaves an unchanged document's passages and vectors in place.

The consolidated text goes through the corpus [redactor](corpus.md#redaction)
before it is stored: precedents are resolutions about real complainants, so the
stored body and every passage carry the same privacy labels as corpus text. The
build hash covers the redactor version, so a new redactor rebuilds the index.

## Sources

`apps/api/src/reclamos_api/rules/sources.py` owns every source's slug, title,
kind, approval, text date, PDF URL, and amendments. The indexed material is:

- the 2021 TRASU lineamientos for appeals and complaints;
- the TUO del Reglamento de Reclamos, Res. 099-2022-CD/OSIPTEL;
- the Norma de las Condiciones de Uso, Res. 132-2025-CD/OSIPTEL;
- the six TRASU precedentes de observancia obligatoria;
- the Tribunal de Apelaciones precedents in Res. 072-2025-TA/OSIPTEL.

The Reglamento source is the SPIJ consolidated edition dated 2026-08-04. Its
article notes already apply the earlier amendments. Res. 000129-2026-CD is the
only later amendment. It modifies articles 11, 14, 25, 29, 30, 36, 41, 48, 49,
50, 58, 70, 80, 84, 96, 99, 100, 103 and 104, annexes 2 and 5, incorporates
articles 19-A, 25-A, 25-B and 84-A and the Novena Disposición Complementaria
Final, and repeals articles 83 and 85 to 88 and annex 1. The Condiciones source
already includes its Res. 035-2026-CD change in an article note.

The source list excludes Res. 086-2026-CD because it publishes a draft for
comments, not an effective norm.

## Consolidation

`sync.py` splits regulations into articles, final dispositions and annexes. It
uses a SPIJ article note's replacement text and citation instead of the
superseded text. A `derogado` note removes the article. An amendment declares
the labels it modifies, incorporates and repeals. The indexer checks that every
declared modified or repealed label exists in the text it replaces and that
every declared new or modified label exists in the amending text. It also
rejects an amendment dated on or before its base text. It stops when either
check fails.

Amendments apply in text-date order. A modified or incorporated passage keeps
the approving resolution and text date of that amendment. A repealed passage is
not indexed. This makes a served citation name the resolution from which that
text comes, such as
`Artículo 48, texto modificado por la Res. 000129-2026-CD/OSIPTEL`.

Lineamientos are split by their numbered heading. Precedents discard the
resolution heading and procedural opening before their sumilla. The sanctions
precedent from Res. 072-2025-TA/OSIPTEL remains indexed but is not searched for
visitor claims. The corpus resolution rows for matching TRASU expedientes are
marked as precedents when the rules indexer runs. The current corpus has the
06982-2003 and 07837-2003 precedents.

## Search and response

`POST /cases` searches `rule_passages` separately from corpus chunks and adds a
`rules` list of at most three passages only when the case search found a similar
case. Every item carries the title, kind, article or section, approving or
amending norm, text date, PDF URL and literal source text. The route uses the
same `embedding_model` guard as corpus search.

`RULES_MIN_SIMILARITY` defaults to `0.83` and `RULES_MIN_TEXT_RANK` defaults to
`0.02`. A passage must pass both gates: cosine similarity and a Spanish
full-text rank. On 2026-11-17, the 128 judged questions produced rules for 109
of 116 answerable questions. The case gate prevented rules for six of 12
unanswerable questions; only q117 and q122 passed both gates, and both already
returned cases. Re-evaluate both values against the judged questions in
`packages/eval` whenever the source set or embedding model changes.
