import { Badge } from "@gitbutler/but-ui-react/Badge.tsx";
import { Button } from "@gitbutler/but-ui-react/Button.tsx";
import card from "@gitbutler/but-ui-react/card.module.css";
import { MetaPart } from "@gitbutler/but-ui-react/MetaPart.tsx";
import { TextLink } from "@gitbutler/but-ui-react/TextLink.tsx";
import { useId, useState } from "react";
import type { CardPoint, FoundCase } from "./api";
import styles from "./CaseCard.module.css";
import { CARD_FIELDS, dateLabel, outcomeBadge, outcomeLabel } from "./labels";

type Field = { name: string; title: string; points: CardPoint[] };

export function CaseCard({ found }: { found: FoundCase }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const fields: Field[] = CARD_FIELDS.flatMap(([name, title]) => {
    const points = found.card?.[name];
    return points?.length ? [{ name, title, points }] : [];
  });
  const claim = found.card?.claim?.[0];
  // Closed, the card shows the claim as its title, one point of the
  // tribunal's reasoning and one of what it ordered: what a visitor compares
  // with their problem, and what came of the case.
  const reasons = fields.find((field) => field.name === "reasoning");
  const orders = fields.find((field) => field.name === "orders");
  const closed =
    reasons || orders
      ? [reasons, orders].filter((field) => field !== undefined)
      : fields.filter((field) => field.name !== "claim").slice(0, 1);
  const summary = closed.map((field) => ({
    ...field,
    points: field.points.slice(0, 1),
  }));
  const shown = (claim ? 1 : 0) + summary.length;
  const more = fields.reduce((n, field) => n + field.points.length, 0) > shown;
  const reference = found.number
    ? `Resolución ${found.number}`
    : `Expediente ${found.expediente}`;
  return (
    <article className={`${card.card} ${styles.case}`}>
      <header className={styles.head}>
        <Badge variant={outcomeBadge(found.outcome)}>
          {outcomeLabel(found.outcome)}
        </Badge>
        <h3 className="text-15 text-semibold text-balance">
          {claim ? claim.text : reference}
        </h3>
        <div className={`text-12 ${styles.meta}`}>
          {found.operator && (
            <MetaPart icon="globe">
              {found.brand
                ? `${found.brand} (${companyName(found.operator)})`
                : companyName(found.operator)}
            </MetaPart>
          )}
          {found.date && (
            <MetaPart icon="clock">{dateLabel(found.date)}</MetaPart>
          )}
          {claim && <MetaPart icon="file-text">{reference}</MetaPart>}
        </div>
      </header>
      <div id={bodyId} className={styles.body}>
        {fields.length ? (
          (open ? fields : summary).map((field) => (
            <Part key={field.name} {...field} />
          ))
        ) : (
          <section className={styles.part}>
            <h4 className={`text-13 text-semibold ${styles.title}`}>
              Pasaje más parecido
            </h4>
            <p className={`text-13 ${styles.quote}`}>{found.passage.text}</p>
          </section>
        )}
      </div>
      <footer className={styles.foot}>
        {more && (
          <Button
            size="small"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen(!open)}
          >
            {open ? "Ver menos" : "Ver el caso completo"}
          </Button>
        )}
        <span className={styles.links}>
          {found.pdf_url && (
            <TextLink
              className="text-13"
              href={found.pdf_url}
              target="_blank"
              rel="noreferrer"
            >
              Abrir la resolución (PDF)
            </TextLink>
          )}
          <TextLink
            className="text-13"
            href={found.url}
            target="_blank"
            rel="noreferrer"
          >
            Ver en gob.pe
          </TextLink>
        </span>
      </footer>
    </article>
  );
}

function Part({ title, points }: Field) {
  return (
    <section className={styles.part}>
      <h4 className={`text-13 text-semibold ${styles.title}`}>{title}</h4>
      <ul className={styles.points}>
        {points.map((point) => (
          <li key={point.quote}>
            <p className="text-prose">{point.text}</p>
            <details className={styles.cite}>
              <summary className="text-12">Ver cita</summary>
              <blockquote className={`text-13 ${styles.quote}`}>
                «{point.quote}»
              </blockquote>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Resolutions write the company in capitals: "TELEFONICA DEL PERU S.A.A.". The
// legal suffix keeps its capitals.
function companyName(operator: string): string {
  return operator
    .split(" ")
    .map((word) => {
      if (/^[A-Z]\./.test(word) || word.length <= 1) return word;
      if (word === "DEL" || word === "DE") return word.toLowerCase();
      return word[0] + word.slice(1).toLowerCase();
    })
    .join(" ");
}
