import { Badge } from "@gitbutler/but-ui-react/Badge.tsx";
import { Banner } from "@gitbutler/but-ui-react/Banner.tsx";
import { Button } from "@gitbutler/but-ui-react/Button.tsx";
import { EmptyState } from "@gitbutler/but-ui-react/EmptyState.tsx";
import {
  FieldLabelStyles,
  FieldRootStyles,
  FieldTextareaStyles,
} from "@gitbutler/but-ui-react/Field.tsx";
import { Select } from "@gitbutler/but-ui-react/Select.tsx";
import { SkeletonBone } from "@gitbutler/but-ui-react/SkeletonBone.tsx";
import { type FormEvent, useRef, useState } from "react";
import { type CasesResponse, findCases, MAX_QUERY_CHARS } from "./api";
import styles from "./App.module.css";
import { CaseCard } from "./CaseCard";
import { CLAIM_TYPES, outcomeBadge, outcomeLabel } from "./labels";

type Search =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "failed" }
  | { state: "done"; response: CasesResponse };

type Request = { query: string; claimType: string };

export function App() {
  const [query, setQuery] = useState("");
  const [claimType, setClaimType] = useState("");
  const [search, setSearch] = useState<Search>({ state: "idle" });
  const [sent, setSent] = useState<Request | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  async function run(request: Request) {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setSent(request);
    setSearch({ state: "loading" });
    try {
      const response = await findCases(
        {
          query: request.query,
          ...(request.claimType && { claim_type: request.claimType }),
        },
        controller.signal,
      );
      setSearch({ state: "done", response });
    } catch (error) {
      if (!controller.signal.aborted) {
        console.error(error);
        setSearch({ state: "failed" });
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    if (text) void run({ query: text, claimType });
  }

  function searchAllTypes() {
    if (!sent) return;
    setClaimType("");
    void run({ ...sent, claimType: "" });
  }

  return (
    <main className={styles.shell}>
      <header className={styles.intro}>
        <h1 className="text-h1 text-balance">Casos parecidos a tu reclamo</h1>
        <p className={`text-prose ${styles.lead}`}>
          Cuenta tu problema con tu empresa de telefonía, internet o cable. Te
          mostramos resoluciones públicas del tribunal de OSIPTEL sobre casos
          parecidos, con la cita de la resolución que respalda cada punto.
        </p>
      </header>

      <form className={styles.search} onSubmit={submit}>
        <FieldRootStyles>
          <FieldLabelStyles htmlFor="query">Tu problema</FieldLabelStyles>
          <FieldTextareaStyles
            id="query"
            className={styles.query}
            value={query}
            maxLength={MAX_QUERY_CHARS}
            rows={4}
            required
            placeholder="Por ejemplo: me cobran un plan que nunca contraté y la empresa no lo quiere anular."
            onChange={(event) => setQuery(event.target.value)}
          />
        </FieldRootStyles>
        <Select
          label="Tipo de problema"
          placeholder="Cualquiera"
          items={CLAIM_TYPES}
          value={claimType || null}
          onValueChange={(value) => setClaimType(value ?? "")}
        />
        <Button
          type="submit"
          variant="pop"
          className={styles.submit}
          disabled={search.state === "loading"}
        >
          {search.state === "loading" ? "Buscando…" : "Buscar casos"}
        </Button>
      </form>

      <div aria-live="polite">
        <Results
          search={search}
          onRetry={() => sent && void run(sent)}
          onSearchAllTypes={sent?.claimType ? searchAllTypes : undefined}
        />
      </div>

      <p className={`text-12 text-body ${styles.notice}`}>
        No es asesoría legal. Cada caso se decidió por sus propios hechos, y un
        caso parecido no asegura el resultado del tuyo.
      </p>
    </main>
  );
}

function Results({
  search,
  onRetry,
  onSearchAllTypes,
}: {
  search: Search;
  onRetry: () => void;
  onSearchAllTypes?: () => void;
}) {
  if (search.state === "idle") return null;
  if (search.state === "loading") return <Loading />;
  if (search.state === "failed") {
    return (
      <Banner
        variant="danger"
        title="No pudimos buscar ahora"
        action={
          <Button variant="ghost" size="small" onClick={onRetry}>
            Reintentar
          </Button>
        }
      >
        Intenta de nuevo en unos minutos.
      </Banner>
    );
  }
  const { response } = search;
  if (response.outcome === "no_similar_case") {
    return (
      <EmptyState
        className={styles.empty}
        illustration="papers"
        title="No encontramos casos lo bastante parecidos"
        description="Prueba contar el problema con otras palabras o con más detalle."
      >
        {onSearchAllTypes && (
          <Button onClick={onSearchAllTypes}>Buscar en todos los tipos</Button>
        )}
      </EmptyState>
    );
  }
  return (
    <section className={styles.results} aria-labelledby="results-title">
      <header className={styles.resultsHead}>
        <h2 id="results-title" className="text-h3">
          Casos parecidos
        </h2>
        <p className={styles.tally}>
          {Object.entries(response.outcomes).map(([outcome, count]) => (
            <Badge key={outcome} variant={outcomeBadge(outcome)}>
              {`${outcomeLabel(outcome)}: ${count}`}
            </Badge>
          ))}
        </p>
        {response.brands.length > 0 && (
          <p className={`text-13 ${styles.brands}`}>
            Primero, casos con {BRAND_LIST.format(response.brands)}.
          </p>
        )}
      </header>
      {response.cases.map((found) => (
        <CaseCard key={found.resolution_id} found={found} />
      ))}
    </section>
  );
}

const BRAND_LIST = new Intl.ListFormat("es", { type: "disjunction" });

function Loading() {
  return (
    <div className={styles.results} aria-busy="true" aria-label="Buscando">
      {[0, 1].map((index) => (
        <div key={index} className={styles.bones}>
          <SkeletonBone className="text-11" width="6rem" />
          <SkeletonBone className="text-15" width="70%" />
          <SkeletonBone className="text-13" />
          <SkeletonBone className="text-13" width="85%" />
        </div>
      ))}
    </div>
  );
}
