import type { BadgeVariant } from "@gitbutler/but-ui-react/Badge.tsx";
import type { CardField } from "./api";

// The claim types a visitor can pick. `procedural` is left out: it names
// resolutions about the appeal itself, not a kind of problem.
export const CLAIM_TYPES = [
  { value: "billing", label: "Cobros y recibos" },
  { value: "service_cut", label: "Corte, baja o suspensión" },
  { value: "service_quality", label: "Calidad, averías o instalación" },
  { value: "unrequested_contract", label: "Servicio que no pedí" },
  { value: "contract_terms", label: "Contrato, ofertas o promociones" },
  { value: "equipment", label: "Equipos y garantía" },
  { value: "porting", label: "Portabilidad" },
];

// The colour says how the claim ended for the user: won, lost, or dismissed
// before the tribunal looked at the merits.
const OUTCOME_BADGES: Record<string, BadgeVariant> = {
  fundado: "safe",
  fundado_en_parte: "safe",
  infundado: "danger",
  improcedente: "warn",
};

export function outcomeBadge(outcome: string | null): BadgeVariant {
  return (outcome && OUTCOME_BADGES[outcome]) || "lightGray";
}

const OUTCOMES: Record<string, string> = {
  fundado: "Fundado",
  fundado_en_parte: "Fundado en parte",
  infundado: "Infundado",
  improcedente: "Improcedente",
  mixto: "Mixto",
  sin_efecto: "Sin efecto",
};

export function outcomeLabel(outcome: string | null): string {
  return (outcome && OUTCOMES[outcome]) ?? "Resultado sin leer";
}

export const CARD_FIELDS: [CardField, string][] = [
  ["claim", "Qué reclamó el usuario"],
  ["operator_position", "Qué respondió la empresa"],
  ["reasoning", "Por qué decidió así el tribunal"],
  ["evidence", "Pruebas"],
  ["orders", "Qué ordenó el tribunal"],
];

const DATE = new Intl.DateTimeFormat("es-PE", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

export function dateLabel(isoDate: string): string {
  return DATE.format(new Date(`${isoDate}T00:00:00Z`));
}
