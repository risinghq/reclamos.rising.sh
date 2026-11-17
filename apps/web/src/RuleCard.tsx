import card from "@gitbutler/but-ui-react/card.module.css";
import { TextLink } from "@gitbutler/but-ui-react/TextLink.tsx";
import type { FoundRule } from "./api";
import styles from "./RuleCard.module.css";

export function RuleCard({ rule }: { rule: FoundRule }) {
  return (
    <article className={`${card.card} ${styles.rule}`}>
      <header className={styles.head}>
        <h3 className="text-15 text-semibold text-balance">{rule.title}</h3>
        <p className={`text-12 ${styles.citation}`}>
          {rule.label}. {rule.approved_by}. Texto de {dateLabel(rule.text_date)}
          .
        </p>
      </header>
      <p className={`text-prose ${styles.text}`}>{rule.text}</p>
      <footer className={styles.foot}>
        <TextLink
          className="text-13"
          href={rule.pdf_url}
          target="_blank"
          rel="noreferrer"
        >
          Abrir la norma (PDF)
        </TextLink>
      </footer>
    </article>
  );
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("es-PE", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}
