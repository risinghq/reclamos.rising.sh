# Model calls

The offline [cards](cards.md) are the only code that calls a language model. No
route calls one, so a visitor never spends model credit. The code is in
`apps/api/src/reclamos_api/llm/`.

| File        | Owns                                                                                |
| ----------- | ----------------------------------------------------------------------------------- |
| `client.py` | The `LanguageModel` protocol, the Anthropic and OpenRouter clients and model prices |
| `spend.py`  | The cost log `llm_calls` and the limits checked before every call                   |
| `quotes.py` | The rule that a quote is in its text                                                |

## Providers

Each model in `MODELS` names its provider. `model_for` builds the client of that
provider, so `CARD_MODEL` and `JUDGE_MODEL` may use different ones. A command
exits when the key of its model's provider is unset.

- Anthropic serves the `claude-*` models through the Messages API.
- OpenRouter serves the other models through its Chat Completions API. A request
  sets `provider.max_price` to the price in `MODELS`, so no dearer endpoint
  serves it and the worst case stays an upper bound. It sets
  `provider.require_parameters`, so only an endpoint that honours the strict
  JSON schema serves it. It turns reasoning off. The ledger records the
  `usage.cost` that OpenRouter reports, which can be below the `MODELS` price.
- A model id ending in `:free` is a free variant. Its `MODELS` price is 0, so
  its `max_price` keeps any paid endpoint from serving it. OpenRouter allows 50
  free requests a day, and 1,000 once the account has bought US$10 of credits.
  An upstream provider can also answer 429 when it is busy, which stops a run.
  Free providers may log prompts. The resolutions are public, so this is
  acceptable for cards.

## Quotes

A quote is in a text when it is at least 20 characters and appears in the text.
The comparison ignores case, accents, runs of whitespace and quote marks,
because models rewrite those. Any other difference fails the quote.

## Spend limits

Every model call goes through `Ledger.complete` in `spend.py`. It checks these
limits in order, and a call that would pass one is never made. It raises
`SpendRefused`.

1. The system prompt and the text together are at most 40,000 characters. A
   caller may pass another cap: a card sends a whole body.
2. The call's worst case is computed: every two characters of prompt count as a
   token, and every output token up to `max_tokens` is used. Spanish runs near
   four characters a token, so the bound is above what a call is billed.
3. The worst case must fit in the run's `Budget` when the caller passes one. The
   card commands always do. A call in flight counts against the budget at its
   worst case until it returns, so concurrent calls of one run cannot pass it
   together.
4. The worst case must fit under `DAILY_USD_CAP`, counted over every row of
   `llm_calls` since midnight in Lima. A transaction-level advisory lock
   serializes the check and the insert of the call's row, so processes that
   share the database cannot both pass the cap that only one fits under.

The row is written before the call with `reserved_usd`, the worst case. A call
in flight counts at that amount. When the call returns, the row gets the token
counts and the billed `usd`. When it fails, it gets the error and a cost:

- A `NotBilled` error counts 0. Both clients raise it for an HTTP error status,
  which neither provider bills.
- Any other error, such as a timeout or a cancelled request, keeps the reserved
  cost, because the provider may have billed the call. OpenRouter answers 200
  with an `error` body when the model fails after it started. Both clients
  raise `ProviderFailed` for that body, a timeout or a lost connection, so a
  batch command can skip the one item and go on.

A process that dies during a call leaves its row with no `usd`, and the row
counts at `reserved_usd` for the rest of the day.

`MODELS` in `client.py` holds each model's price per million tokens and the
setting that turns its thinking off. Thinking tokens count against `max_tokens`,
so a thinking model can spend the whole cap before it writes the reply. A model
missing from `MODELS` cannot be called, because its cost could not be bounded.
The client makes no retries, since each retry is billed again. Each `Prompt`
sets its own timeout: 60 seconds by default, 180 for a card. A timeout can fire
after the model ran, so it keeps the reserved cost.

Spend is a query away:

```sql
SELECT purpose, model, count(*), sum(coalesce(usd, reserved_usd))
FROM llm_calls
WHERE started_at >= now() - interval '1 day'
GROUP BY 1, 2;
```

The Anthropic Console limits the workspace and OpenRouter limits each key. Those
limits are the operator's and sit outside this code.

## Settings

| Variable             | Default | Meaning                                                   |
| -------------------- | ------- | --------------------------------------------------------- |
| `ANTHROPIC_API_KEY`  | unset   | Needed to call a `claude-*` model                         |
| `OPENROUTER_API_KEY` | unset   | Needed to call any other model in `MODELS`                |
| `DAILY_USD_CAP`      | `2.0`   | US dollars all processes together may spend in a Lima day |

## Tests

`apps/api/tests/fakemodel.py` stands in for the model. It records the prompts,
bills fixed token counts, and replies with a function of the prompt.
`test_llm.py` covers the quote rule, the client's request and errors, and the
spend limits against PostgreSQL. The OpenRouter tests answer through
`httpx.MockTransport`. No test calls a provider.
