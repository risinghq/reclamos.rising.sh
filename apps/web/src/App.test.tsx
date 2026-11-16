import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  claim_type: "unrequested_contract",
  outcome: "fundado",
  url: "https://www.gob.pe/institucion/osiptel/normas-legales/1",
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

  it("shows each similar case with its points, their quotes and the source", async () => {
    const sent = answer(200, {
      query: "me cobran un plan",
      outcome: "found",
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
    const [carded, bare] = screen.getAllByRole("article");
    expect(carded).toHaveTextContent("Resolución 00321-2024-TRASU/OSIPTEL");
    expect(carded).toHaveTextContent("Fundado");
    expect(carded).toHaveTextContent("18 de marzo de 2024");
    expect(carded).toHaveTextContent(
      "El usuario niega haber contratado el plan.",
    );
    expect(carded).toHaveTextContent("«no contrató el plan»");
    expect(screen.getAllByRole("link", { name: /gob\.pe/ })[0]).toHaveAttribute(
      "href",
      CASE.url,
    );
    expect(bare).toHaveTextContent("Expediente 1234-2024/TRASU");
    expect(bare).toHaveTextContent("Resultado sin leer");
    expect(bare).toHaveTextContent("El pasaje.");
  });

  it.each([
    [
      "no similar case",
      () =>
        answer(200, {
          query: "x",
          outcome: "no_similar_case",
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
