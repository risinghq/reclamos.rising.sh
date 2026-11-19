import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CasesResponse, FoundCase, FoundRule } from "./api";
import { App } from "./App";

const CASE: FoundCase = {
  resolution_id: 4211,
  expediente: "1234-2024/TRASU",
  sector: "telecom",
  number: "00321-2024-TRASU/OSIPTEL",
  date: "2024-03-18",
  operator: "AMERICA MOVIL PERU S.A.C.",
  brand: "Claro",
  claim_type: "unrequested_contract",
  outcome: "fundado",
  url: "https://www.gob.pe/institucion/osiptel/normas-legales/1",
  pdf_url: "https://cdn.www.gob.pe/uploads/document/file/1/res.pdf",
  similarity: 0.87,
  is_precedent: false,
  passage: {
    ordinal: 3,
    section: "analisis",
    page_start: 2,
    page_end: 2,
    text: "El pasaje.",
  },
  card: {
    claim: [
      {
        text: "El usuario niega haber contratado el plan.",
        quote: "no contrató el plan",
      },
    ],
    reasoning: [
      { text: "La empresa no probó la contratación.", quote: "no acreditó" },
      { text: "No hay grabación de la venta.", quote: "sin grabación" },
    ],
    evidence: [{ text: "El recibo de marzo.", quote: "recibo" }],
    orders: [
      { text: "La empresa debe anular el cobro.", quote: "anular el cobro" },
      { text: "La empresa debe informar en 30 días.", quote: "informar" },
    ],
  },
  statistics: null,
};

const STATISTICS: FoundCase["statistics"] = {
  file_type: "RA",
  source: "https://punku.osiptel.gob.pe/Archivos/Datasets-PUNKU-OSIPTEL.zip",
  cut_on: "2026-07-24",
  concepts: [
    {
      concept: "facturación y cobro",
      detail: "cargo fijo",
      counts: {
        files: 198403,
        first_year: 2017,
        last_year: 2026,
        outcomes: {
          fundado: 31744,
          fundado_en_parte: 33729,
          infundado: 19840,
          improcedente: 95233,
          other: 17857,
        },
      },
      brand: {
        brand: "Claro",
        files: 1000,
        first_year: 2018,
        last_year: 2025,
        outcomes: {
          fundado: 200,
          fundado_en_parte: 100,
          infundado: 300,
          improcedente: 398,
          other: 2,
        },
      },
    },
  ],
};

const RULE: FoundRule = {
  title: "TUO del Reglamento de Reclamos",
  kind: "reglamento",
  label: "Artículo 48",
  approved_by: "Res. 000129-2026-CD/OSIPTEL",
  text_date: "2026-10-03",
  pdf_url: "https://www.osiptel.gob.pe/media/reglamento.pdf",
  text: "La empresa debe responder el reclamo dentro del plazo aplicable.",
};

function answer(status: number, body?: CasesResponse) {
  const fetch = vi.fn<typeof globalThis.fetch>(
    async () => new Response(JSON.stringify(body ?? {}), { status }),
  );
  vi.stubGlobal("fetch", fetch);
  return () => JSON.parse(String(fetch.mock.calls[0]?.[1]?.body));
}

async function searchFor(problem: string, claimType?: string) {
  const user = userEvent.setup();
  render(<App />);
  fireEvent.change(screen.getByLabelText("Tu problema"), {
    target: { value: problem },
  });
  if (claimType) {
    await user.click(
      screen.getByRole("combobox", { name: "Tipo de problema" }),
    );
    await user.click(await screen.findByRole("option", { name: claimType }));
  }
  await user.click(screen.getByRole("button", { name: "Buscar casos" }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("search page", () => {
  it("states the source and the legal boundary in Spanish", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "reclamo",
    );
    expect(screen.getByText(/resoluciones públicas/i)).toBeInTheDocument();
    expect(screen.getByText(/no es asesoría legal/i)).toBeInTheDocument();
  });

  it("names the telecom and electricity and gas sectors", () => {
    render(<App />);

    const lead = screen.getByText(/resoluciones públicas/i);
    expect(lead).toHaveTextContent("telefonía, internet o cable");
    expect(lead).toHaveTextContent("luz o gas");
    expect(lead).toHaveTextContent("OSIPTEL y Osinergmin");
  });

  it("shows each case closed to its claim, one reason and one order, and opens the rest", async () => {
    const sent = answer(200, {
      query: "me cobran un plan",
      outcome: "found",
      sector: "telecom",
      brands: ["Claro"],
      outcomes: { fundado: 1 },
      cases: [
        CASE,
        { ...CASE, resolution_id: 9, number: null, outcome: null, card: null },
      ],
      rules: [RULE],
    });

    await searchFor("  me cobran un plan  ", "Cobros y recibos");

    expect(
      await screen.findByRole("heading", { name: "Casos parecidos" }),
    ).toBeInTheDocument();
    expect(sent()).toEqual({
      query: "me cobran un plan",
      claim_type: "billing",
    });
    expect(screen.getByText("Primero, casos con Claro.")).toBeInTheDocument();
    const rules = screen.getByRole("region", { name: "Normas que aplican" });
    expect(rules).toHaveTextContent("Normas que aplican");
    expect(rules).toHaveTextContent(RULE.text);
    expect(rules).toHaveTextContent("Artículo 48");
    expect(
      within(rules).getByRole("link", { name: "Abrir la norma (PDF)" }),
    ).toHaveAttribute("href", RULE.pdf_url);
    const [carded, bare] = screen.getAllByRole("article");
    const inCard = within(carded);
    expect(inCard.getByRole("heading", { level: 3 })).toHaveTextContent(
      "El usuario niega haber contratado el plan.",
    );
    expect(carded).toHaveTextContent("Fundado");
    expect(carded).toHaveTextContent("Claro (America Movil Peru S.A.C.)");
    expect(carded).toHaveTextContent("18 de marzo de 2024");
    expect(carded).toHaveTextContent("Resolución 00321-2024-TRASU/OSIPTEL");
    expect(carded).toHaveTextContent("La empresa no probó la contratación.");
    expect(carded).toHaveTextContent("Qué ordenó el tribunal");
    expect(carded).toHaveTextContent("La empresa debe anular el cobro.");
    expect(carded).not.toHaveTextContent("No hay grabación de la venta.");
    expect(carded).not.toHaveTextContent("El recibo de marzo.");
    expect(carded).not.toHaveTextContent(
      "La empresa debe informar en 30 días.",
    );
    expect(inCard.getByText("«no acreditó»")).not.toBeVisible();
    expect(
      inCard.getByRole("link", { name: "Abrir la resolución (PDF)" }),
    ).toHaveAttribute("href", CASE.pdf_url);
    expect(inCard.getByRole("link", { name: "Ver en gob.pe" })).toHaveAttribute(
      "href",
      CASE.url,
    );

    const user = userEvent.setup();
    await user.click(
      inCard.getByRole("button", { name: "Ver el caso completo" }),
    );
    expect(carded).toHaveTextContent("No hay grabación de la venta.");
    expect(carded).toHaveTextContent("Pruebas");
    expect(carded).toHaveTextContent("El recibo de marzo.");
    expect(carded).toHaveTextContent("La empresa debe informar en 30 días.");
    await user.click(inCard.getAllByText("Ver cita")[0]!);
    expect(inCard.getByText("«no contrató el plan»")).toBeVisible();

    expect(bare).toHaveTextContent("Expediente 1234-2024/TRASU");
    expect(bare).toHaveTextContent("Resultado sin leer");
    expect(bare).toHaveTextContent("El pasaje.");
    expect(within(bare).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows how the tribunal decided files like a matched case, and nothing for an unmatched one", async () => {
    answer(200, {
      query: "me cobran el cargo fijo",
      outcome: "found",
      sector: "telecom",
      brands: [],
      outcomes: { fundado: 2 },
      cases: [
        { ...CASE, statistics: STATISTICS },
        { ...CASE, resolution_id: 9 },
      ],
      rules: [],
    });

    await searchFor("me cobran el cargo fijo");

    const [matched, unmatched] = await screen.findAllByRole("article");
    const inCard = within(matched!);
    expect(
      inCard.getByRole("heading", {
        name: "Cómo decidió el tribunal casos como este",
      }),
    ).toBeInTheDocument();
    expect(matched).toHaveTextContent(
      "Desde 2017 el tribunal resolvió 198,403 apelaciones por facturación y cobro (cargo fijo): 16% fundadas, 17% fundadas en parte, 10% infundadas, 48% improcedentes y 9% terminó de otra forma.",
    );
    expect(matched).toHaveTextContent(
      "Contra Claro, 1,000 apelaciones: 20% fundadas, 10% fundadas en parte, 30% infundadas, 40% improcedentes y menos de 1% terminó de otra forma.",
    );
    expect(matched).toHaveTextContent(
      "Improcedentes: no resolvió el fondo del pedido",
    );
    expect(matched).toHaveTextContent("De otra forma:");
    expect(matched).toHaveTextContent(
      "Son resultados pasados, no una predicción para tu caso.",
    );
    expect(matched).toHaveTextContent("con datos al 24 de julio de 2026");
    expect(inCard.getByRole("link", { name: "PUNKU" })).toHaveAttribute(
      "href",
      "https://punku.osiptel.gob.pe",
    );
    expect(matched).not.toHaveTextContent("—");
    expect(unmatched).not.toHaveTextContent("Cómo decidió el tribunal");
  });

  it.each([
    [
      "no similar case",
      () =>
        answer(200, {
          query: "x",
          outcome: "no_similar_case",
          sector: null,
          brands: [],
          outcomes: {},
          cases: [],
          rules: [],
        }),
      /no encontramos casos/i,
    ],
    ["an API error", () => answer(503), /no pudimos buscar/i],
  ])("explains %s without showing cases", async (_, respond, message) => {
    const sent = respond();

    await searchFor("me cortaron el internet");

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(sent()).toEqual({
      query: "me cortaron el internet",
    });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });
});
