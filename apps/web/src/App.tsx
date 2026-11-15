import { type FormEvent, useRef, useState } from "react";
import { type CasesResponse, findCases, MAX_QUERY_CHARS } from "./api";
import { CaseCard } from "./CaseCard";
import { CLAIM_TYPES, outcomeLabel } from "./labels";
import "./App.css";

type Search =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "failed" }
  | { state: "done"; response: CasesResponse };

export function App() {
  const [query, setQuery] = useState("");
  const [claimType, setClaimType] = useState("");
  const [search, setSearch] = useState<Search>({ state: "idle" });
  const inFlight = useRef<AbortController | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    if (!text) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setSearch({ state: "loading" });
    try {
      const response = await findCases(
        { query: text, ...(claimType && { claim_type: claimType }) },
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

  return (
    <main className="shell">
      <header className="intro-block">
        <p className="eyebrow">OSIPTEL · TRASU</p>
        <h1>Casos parecidos a tu reclamo.</h1>
        <p className="intro">
          Cuenta tu problema con tu empresa de telefonía, internet o cable. Te
          mostramos resoluciones públicas del tribunal de OSIPTEL sobre casos
          parecidos, con la cita de la resolución que respalda cada punto.
        </p>
      </header>

      <form className="search" onSubmit={submit}>
        <label htmlFor="query">Tu problema</label>
        <textarea
          id="query"
          value={query}
          maxLength={MAX_QUERY_CHARS}
          rows={4}
          required
          placeholder="Por ejemplo: me cobran un plan que nunca contraté y la empresa no lo quiere anular."
          onChange={(event) => setQuery(event.target.value)}
        />
        <label htmlFor="claim-type">Tipo de problema</label>
        <select
          id="claim-type"
          value={claimType}
          onChange={(event) => setClaimType(event.target.value)}
        >
          <option value="">Cualquiera</option>
          {CLAIM_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button type="submit" disabled={search.state === "loading"}>
          {search.state === "loading" ? "Buscando…" : "Buscar casos"}
        </button>
      </form>

      <Results search={search} />

      <p className="notice">
        No es asesoría legal. Cada caso se decidió por sus propios hechos, y un
        caso parecido no asegura el resultado del tuyo.
      </p>
    </main>
  );
}

function Results({ search }: { search: Search }) {
  if (search.state === "idle" || search.state === "loading") return null;
  if (search.state === "failed") {
    return (
      <p className="message" role="alert">
        No pudimos buscar ahora. Intenta de nuevo en unos minutos.
      </p>
    );
  }
  const { response } = search;
  if (response.outcome === "no_similar_case") {
    return (
      <p className="message" role="status">
        No encontramos casos lo bastante parecidos. Prueba contar el problema
        con otras palabras o sin elegir un tipo.
      </p>
    );
  }
  return (
    <section className="results" aria-labelledby="results-title">
      <h2 id="results-title">Casos parecidos</h2>
      <p className="tally">
        {Object.entries(response.outcomes)
          .map(([outcome, count]) => `${outcomeLabel(outcome)}: ${count}`)
          .join(" · ")}
      </p>
      {response.cases.map((found) => (
        <CaseCard key={found.resolution_id} found={found} />
      ))}
    </section>
  );
}
