# Cards

A case card says what one resolution decided, in five short fields a reader can
compare with their own case. Cards are written offline by a language model and
stored in the `cards` table. [`POST /cases`](cases.md) serves them with no model
call, so visitors never spend model credit. The code is in
`apps/api/src/reclamos_api/cards/`.

| File            | Owns                                                        |
| --------------- | ----------------------------------------------------------- |
| `card.py`       | The card prompt, its schema and the quote check of a reply  |
| `judge.py`      | The judge that reads each checked point against its quote   |
| `repository.py` | The `cards` table: stale cards, writes, verdicts and report |
| `commands.py`   | `reclamos cards build`, `judge` and `report`                |

## The card

`SYSTEMS` in `card.py` holds one prompt per sector. The prompts differ only in
the tribunal they name — the TRASU of OSIPTEL for `telecom`, the JARU of
Osinergmin for `energy` — and in what the sector calls the company: "empresa
operadora" for telecom, "empresa concesionaria o distribuidora" for energy. The
fields, the quote rules and the readings below are the same for both.

The card model reads the whole body of one resolution and replies in a JSON
schema with these fields:

| Field               | Says                                                         |
| ------------------- | ------------------------------------------------------------ |
| `claim`             | What the user claimed and asked for                          |
| `operator_position` | What the operator said or decided before the appeal or queja |
| `reasoning`         | Why the tribunal decided as it did                           |
| `evidence`          | The evidence that decided the case, or the evidence missing  |
| `orders`            | What the tribunal ordered the operator to do, or declared    |

`orders` comes from the resolutive part: annul a charge, refund an amount,
restore the service, report back. It says what the tribunal ordered, not whether
the operator complied: a resolution is written before the operator acts on it.

Each field is a list of up to three points, most important first. A point is a
quote copied from the body and one plain sentence that says only what that quote
says. The schema puts the quote before the sentence, so the model copies the
quote first and writes the sentence from it. Before this order, the model wrote
sentences from the whole body and attached short quotes that backed only part of
them. A visitor can check each sentence against its own quote.

The reply also holds three readings: `outcome`, `operator` and `resolved_on`,
each with a quote. The number, operator and outcome a page shows come from
[parse](corpus.md), never from the model. The readings exist to audit parse.

`check_card` keeps only what the body backs:

- A quote survives when it is in the body by the [quote rule](llm.md#quotes): at
  least 20 characters, comparing without case, accents, runs of whitespace or
  quote marks.
- A point survives when it has a sentence and its quote is in the body. The
  first three surviving points of a field are kept. A field with no point left
  is dropped.
- A reading survives when its value is valid and its quote is in the body. An
  outcome must be one of the parse outcomes and a date must be a real date. A
  reading the model leaves empty has no quote, so it is dropped.
- Everything dropped goes to the card's `rejected` list, so the report can count
  it.

A reply cut at the token cap, or one that is not JSON, writes no card. The run
prints its resolution id as unreadable. A call that times out or loses its
connection skips only its own card the same way, and the next run writes it.

A card is current while its `prompt_version` and `body_sha256` match the code
and the body. `PROMPT_VERSIONS` hashes each sector's system prompt and the
shared schema, so a prompt change makes only that sector's cards stale. A
re-parsed body makes its own card stale. Writing a card again clears its
verdict.

The card reads the extracted body, but what it stores is redacted: the
[redactor](corpus.md#pipeline) runs over the checked fields, readings and
rejected quotes before the row is written, and `reclamos cards redact` applies
it to stored cards. `body_sha256` still hashes `body`, so redaction does not
regenerate a card.

## Judge

`reclamos cards judge` sends each current card without a current verdict to the
judge model. The judge reads the numbered points and their quotes only, not the
body. The quotes have already passed the check, so a point its quote backs is
backed by the body. Another point's quote does not back it. The judge lists each
point its quote does not back: its field, its number counted from 1 and the
unbacked words of its sentence. A card with an empty list is faithful.
[`POST /cases`](cases.md) serves only the points the judge did not list.

A verdict is current while its `judge_version` matches the sector's
`JUDGE_VERSIONS` entry, the hash of that sector's judge prompt and the shared
schema. `SYSTEMS` in `judge.py` holds one judge prompt per sector, differing
like the card prompts. A judge change makes only that sector's verdicts stale,
and the next `judge` run judges those cards again.

On a pilot of 10 cards (2026-11-15), 82% of points were served. Most of the
judge's errors were strict: it flagged points that their quote backs. A strict
error hides a good point and never serves a bad one.

The full run (2026-11-15) wrote and judged 299 cards for US$9.45 in cards. The
judge found 42 cards faithful (14%), and 1,924 of 2,309 points (83.3%) are
served. A card the judge flags still serves its other points, so the share of
faithful cards matters less than the share of served points.

## Commands

The commands run on a host with the key of their model's provider set
([providers](llm.md#providers)). Each model call goes through the
[spend limits](llm.md#spend-limits) and logs its row in `llm_calls`, with
purpose `card` or `judge`.

`reclamos cards build --budget-usd N` writes a card for every resolution with a
body and no current card, smallest id first. It stops before the call that could
take the run past `N` and prints where it stopped. A call in flight counts at
its worst case, so `--concurrency` cannot pass the budget. A call the API
refuses, such as one past the Console's workspace usage limit, stops the run the
same way, because every later call would be refused too. The next run writes
only the cards still missing.

| Flag              | Meaning                                        |
| ----------------- | ---------------------------------------------- |
| `--budget-usd`    | The most the run may spend. Required           |
| `--concurrency N` | Calls in flight at once. The default is 4      |
| `--limit N`       | Write at most N cards (`build` only)           |
| `--sector S`      | Only `telecom` or `energy`. Default: every one |

`reclamos cards judge --budget-usd N` takes the same flags but `--limit`.

`reclamos cards report` makes no call and takes `--sector` too. It prints:

- the cards, how many are current, and their cost;
- how many points each field kept, over the current cards;
- the points and readings the check dropped;
- the share of judged cards the judge found faithful, and the unsupported points
  by field;
- the share of judged points that are served;
- each reading that disagrees with parse, and each reading where parse has no
  value.

The operator reading matches parse when their letters match, so "América Móvil
Perú S.A.C." matches "AMERICA MOVIL PERU S.A.C.". A date matches on its value.

## Limits

A card prompt is at most 60,000 characters, above the longest body in the corpus
(47,053 characters, 2026-11-14). The reply is capped at 3,000 tokens and the
call times out after 180 seconds. A card call on the longest body reserves about
US$0.08 with Sonnet 5.5.

## Settings

| Variable      | Default                             | Meaning          |
| ------------- | ----------------------------------- | ---------------- |
| `CARD_MODEL`  | `nvidia/nemotron-3.5-super-vl:free` | Writes the cards |
| `JUDGE_MODEL` | `claude-sonnet-5-5`                 | Judges the cards |

Either may name any model in `MODELS` in `llm/client.py`.

The writer is a free model because the judge drops every point it cannot
support, so a weaker writer costs points, not accuracy. A pilot on 2026-11-16
wrote cards for the same 10 resolutions with each writer, and Sonnet judged
them:

| Writer                              | Cards | Faithful | Points served | Cost    |
| ----------------------------------- | ----- | -------- | ------------- | ------- |
| `claude-sonnet-5-5`                 | 10    | 1 of 10  | 64 of 78      | US$0.33 |
| `nvidia/nemotron-3.5-super-vl:free` | 9     | 3 of 8   | 53 of 62      | US$0    |
| `inclusionai/ling-3.2-flash:free`   | 4     | 2 of 4   | 26 of 28      | US$0    |

Nemotron cut one reply at the token cap and had 40 points dropped for a quote
not in the text, against Sonnet's 13. Ling stopped on upstream rate limits after
4 cards. At 50 free requests a day a full rebuild of 300 cards takes six days.
The build resumes where it stopped.

## Tests

`test_cards.py` builds cards from the fixture resolutions with the fake model.
It walks the flow: a run stopped by its budget, one stopped by the API's
refusal, a run that finishes, a third that writes nothing, the quote check, the
judge and the report. No test calls a provider.
