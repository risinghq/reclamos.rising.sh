import type { CardField } from "./api";

// The claim types a visitor can pick. `procedural` is left out: it names
// resolutions about the appeal itself, not a kind of problem.
export const CLAIM_TYPES: [string, string][] = [
  ["billing", "Cobros y recibos"],
  ["service_cut", "Corte, baja o suspensión"],
  ["service_quality", "Calidad, averías o instalación"],
  ["unrequested_contract", "Servicio que no pedí"],
  ["contract_terms", "Contrato, ofertas o promociones"],
  ["equipment", "Equipos y garantía"],
  ["porting", "Portabilidad"],
];

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
