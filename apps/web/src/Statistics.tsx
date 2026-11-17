import { TextLink } from "@gitbutler/but-ui-react/TextLink.tsx";
import type {
  ConceptStatistics,
  Outcome,
  OutcomeCounts,
  Statistics as Counted,
} from "./api";
import { dateLabel } from "./labels";
import styles from "./Statistics.module.css";

const NUMBER = new Intl.NumberFormat("es-PE");
const PERCENT = new Intl.NumberFormat("es-PE", {
  style: "percent",
  maximumFractionDigits: 0,
});

const DECIDED: [Outcome, string, string][] = [
  ["fundado", "fundadas", "el tribunal dio la razón al usuario."],
  [
    "fundado_en_parte",
    "fundadas en parte",
    "le dio la razón en una parte de lo que pidió.",
  ],
  ["infundado", "infundadas", "dio la razón a la empresa."],
  [
    "improcedente",
    "improcedentes",
    "no resolvió el fondo del pedido, por ejemplo porque se presentó fuera de plazo o porque la materia no era reclamable.",
  ],
];

const OTHER =
  "el expediente se archivó, se dio por concluido, se acumuló a otro, se dejó sin efecto o se anuló.";

const FILES = {
  RA: ["apelación", "apelaciones"],
  RQJ: ["queja", "quejas"],
} as const;

export function Statistics({ statistics }: { statistics: Counted }) {
  const [one, many] = FILES[statistics.file_type];
  const other = statistics.concepts.some(
    ({ counts }) => counts.outcomes.other > 0,
  );
  return (
    <section className={styles.statistics}>
      <h4 className="text-13 text-semibold">
        Cómo decidió el tribunal casos como este
      </h4>
      <ul className={styles.concepts}>
        {statistics.concepts.map((concept) => (
          <li key={`${concept.concept}/${concept.detail ?? ""}`}>
            <p className="text-prose">
              {`Desde ${concept.counts.first_year} el tribunal resolvió ${files(concept.counts, one, many)} por ${subject(concept)}: ${shares(concept.counts)}.`}
            </p>
            {concept.brand && (
              <p className={`text-13 ${styles.muted}`}>
                {`Contra ${concept.brand.brand}, ${files(concept.brand, one, many)}: ${shares(concept.brand)}.`}
              </p>
            )}
          </li>
        ))}
      </ul>
      <dl className={`text-12 ${styles.terms}`}>
        {DECIDED.map(([outcome, label, meaning]) => (
          <div key={outcome}>
            <dt>{capitalized(label)}:</dt> <dd>{meaning}</dd>
          </div>
        ))}
        {other && (
          <div>
            <dt>De otra forma:</dt> <dd>{OTHER}</dd>
          </div>
        )}
      </dl>
      <p className={`text-12 ${styles.muted}`}>
        Son resultados pasados, no una predicción para tu caso. Fuente: OSIPTEL,
        portal de datos abiertos{" "}
        <TextLink
          href={new URL(statistics.source).origin}
          target="_blank"
          rel="noreferrer"
        >
          PUNKU
        </TextLink>
        , con datos al {dateLabel(statistics.cut_on)}.
      </p>
    </section>
  );
}

function files(counts: OutcomeCounts, one: string, many: string): string {
  return `${NUMBER.format(counts.files)} ${counts.files === 1 ? one : many}`;
}

function subject({ concept, detail }: ConceptStatistics): string {
  return detail ? `${concept} (${detail})` : concept;
}

function shares(counts: OutcomeCounts): string {
  const parts = DECIDED.map(
    ([outcome, label]) =>
      `${share(counts.outcomes[outcome], counts.files)} ${label}`,
  );
  if (counts.outcomes.other > 0) {
    parts.push(
      `${share(counts.outcomes.other, counts.files)} terminó de otra forma`,
    );
  }
  return `${parts.slice(0, -1).join(", ")} y ${parts.at(-1)}`;
}

function share(count: number, total: number): string {
  const part = count / total;
  return count > 0 && part < 0.005 ? "menos de 1%" : PERCENT.format(part);
}

function capitalized(text: string): string {
  return text[0]!.toUpperCase() + text.slice(1);
}
