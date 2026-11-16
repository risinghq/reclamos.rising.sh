// The POST /cases contract of apps/api, described in docs/cases.md.

export type CardPoint = { text: string; quote: string };

export type CardField =
  | "claim"
  | "operator_position"
  | "reasoning"
  | "evidence";

export type FoundCase = {
  resolution_id: number;
  expediente: string;
  number: string | null;
  date: string | null;
  operator: string | null;
  brand: string | null;
  claim_type: string | null;
  outcome: string | null;
  url: string;
  pdf_url: string | null;
  similarity: number;
  passage: {
    ordinal: number;
    section: string;
    page_start: number;
    page_end: number;
    text: string;
  };
  card: Partial<Record<CardField, CardPoint[]>> | null;
};

export type CasesResponse = {
  query: string;
  outcome: "found" | "no_similar_case";
  brands: string[];
  outcomes: Record<string, number>;
  cases: FoundCase[];
};

export type CasesRequest = { query: string; claim_type?: string };

export const MAX_QUERY_CHARS = 500;

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function findCases(
  request: CasesRequest,
  signal?: AbortSignal,
): Promise<CasesResponse> {
  const response = await fetch(`${API_URL}/cases`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw new Error(`POST /cases answered ${response.status}`);
  }
  return (await response.json()) as CasesResponse;
}
