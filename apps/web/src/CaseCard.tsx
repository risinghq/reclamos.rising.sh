import type { FoundCase } from "./api";
import { CARD_FIELDS, dateLabel, outcomeLabel } from "./labels";

export function CaseCard({ found }: { found: FoundCase }) {
  const fields = CARD_FIELDS.flatMap(([name, title]) => {
    const points = found.card?.[name];
    return points?.length ? [{ name, title, points }] : [];
  });
  return (
    <article className="case">
      <header className="case-head">
        <span className={`outcome outcome-${found.outcome ?? "unknown"}`}>
          {outcomeLabel(found.outcome)}
        </span>
        <h3>
          {found.number
            ? `Resolución ${found.number}`
            : `Expediente ${found.expediente}`}
        </h3>
        <p className="case-meta">
          {[
            found.operator,
            found.date && dateLabel(found.date),
            `Expediente ${found.expediente}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </header>
      {fields.length ? (
        fields.map(({ name, title, points }) => (
          <section key={name} className="field">
            <h4>{title}</h4>
            <ul>
              {points.map((point) => (
                <li key={point.quote}>
                  <p>{point.text}</p>
                  <blockquote>«{point.quote}»</blockquote>
                </li>
              ))}
            </ul>
          </section>
        ))
      ) : (
        <section className="field">
          <h4>Pasaje más parecido</h4>
          <blockquote>{found.passage.text}</blockquote>
        </section>
      )}
      <a className="source" href={found.url} target="_blank" rel="noreferrer">
        Leer la resolución completa en gob.pe
      </a>
    </article>
  );
}
