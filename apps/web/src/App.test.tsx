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
import type { CasesResponse, FoundCase } from "./api";
import { App } from "./App";

const CASE: FoundCase = {
  resolution_id: 4211,
  expediente: "1234-2024/TRASU",
  number: "00321-2024-TRASU/OSIPTEL",
  date: "2024-03-18",
  operator: "AMERICA MOVIL PERU S.A.C.",
  brand: "Claro",
  claim_type: "unrequested_contract",
  outcome: "fundado",
  url: "https://www.gob.pe/institucion/osiptel/normas-legales/1",
  pdf_url: "https://cdn.www.gob.pe/uploads/document/file/1/res.pdf",
  similarity: 0.87,
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

  it("shows each case closed to its claim, one reason and one order, and opens the rest", async () => {
    const sent = answer(200, {
      query: "me cobran un plan",
      outcome: "found",
      brands: ["Claro"],
      outcomes: { fundado: 1 },
      cases: [
        CASE,
        { ...CASE, resolution_id: 9, number: null, outcome: null, card: null },
      ],
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

  it.each([
    [
      "no similar case",
      () =>
        answer(200, {
          query: "x",
          outcome: "no_similar_case",
          brands: [],
          outcomes: {},
          cases: [],
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
