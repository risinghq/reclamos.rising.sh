import { Badge } from "@gitbutler/but-ui-react/Badge.tsx";
import card from "@gitbutler/but-ui-react/card.module.css";
import { MetaPart } from "@gitbutler/but-ui-react/MetaPart.tsx";
import { Section } from "@gitbutler/but-ui-react/Section.tsx";
import { TextLink } from "@gitbutler/but-ui-react/TextLink.tsx";
import type { FoundCase } from "./api";
import styles from "./CaseCard.module.css";
import { CARD_FIELDS, dateLabel, outcomeBadge, outcomeLabel } from "./labels";

export function CaseCard({ found }: { found: FoundCase }) {
  const fields = CARD_FIELDS.flatMap(([name, title]) => {
    const points = found.card?.[name];
    return points?.length ? [{ name, title, points }] : [];
  });
  return (
    <article className={`${card.card} ${styles.case}`}>
      <header className={styles.head}>
        <Badge variant={outcomeBadge(found.outcome)}>
          {outcomeLabel(found.outcome)}
        </Badge>
        <h3 className="text-15 text-semibold">
          {found.number
            ? `Resolución ${found.number}`
            : `Expediente ${found.expediente}`}
        </h3>
        <div className={styles.meta}>
          {found.operator && <MetaPart icon="globe">{found.operator}</MetaPart>}
          {found.date && (
            <MetaPart icon="clock">{dateLabel(found.date)}</MetaPart>
          )}
          {found.number && (
            <MetaPart icon="file-text">Expediente {found.expediente}</MetaPart>
          )}
        </div>
      </header>
      <div className={styles.body}>
        {fields.length ? (
          fields.map(({ name, title, points }) => (
            <Section key={name} title={title}>
              <ul className={styles.points}>
                {points.map((point) => (
                  <li key={point.quote}>
                    <p className="text-prose">{point.text}</p>
                    <blockquote className={`text-13 ${styles.quote}`}>
                      «{point.quote}»
                    </blockquote>
                  </li>
                ))}
              </ul>
            </Section>
          ))
        ) : (
          <Section title="Pasaje más parecido">
            <blockquote className={`text-13 ${styles.quote}`}>
              {found.passage.text}
            </blockquote>
          </Section>
        )}
      </div>
      <footer>
        <TextLink
          className="text-13"
          href={found.url}
          target="_blank"
          rel="noreferrer"
        >
          Leer la resolución completa en gob.pe
        </TextLink>
      </footer>
    </article>
  );
}
