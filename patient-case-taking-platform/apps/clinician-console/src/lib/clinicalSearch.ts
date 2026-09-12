import { clinicalAccessToken, clinicalRole } from "./clinicalSession";

export type ClinicalSourceKind = "signed_summary" | "reviewed_fact";

export type ClinicalSearchHighlight = {
  field: "title" | "content";
  fragments: string[];
};

export type ClinicalSearchHit = {
  record_id: string;
  facility_id: string;
  patient_id: string;
  encounter_id: string;
  document_id: string | null;
  source_kind: ClinicalSourceKind;
  source_id: string;
  title: string;
  entity_type: string | null;
  statement_status: string | null;
  occurred_at: string;
  highlights: ClinicalSearchHighlight[];
};

export type ClinicalSearchResponse = {
  total: number;
  hits: ClinicalSearchHit[];
  facets: {
    source_kinds: Record<string, number>;
    entity_types: Record<string, number>;
  };
  took_ms: number;
  next_cursor: string | null;
};

export type LongitudinalTimelineEvent = {
  record_id: string;
  facility_id: string;
  encounter_id: string;
  document_id: string | null;
  source_kind: ClinicalSourceKind;
  source_id: string;
  title: string;
  details: string[];
  entity_type: string | null;
  statement_status: string | null;
  occurred_at: string;
};

export type LongitudinalTimeline = {
  patient_id: string;
  events: LongitudinalTimelineEvent[];
  summary: {
    total_events: number;
    encounter_count: number;
    signed_summary_count: number;
    reviewed_fact_count: number;
    first_event_at: string | null;
    last_event_at: string | null;
  };
};

export type ClinicalSearchFilters = {
  patientId: string;
  q?: string;
  sourceKind?: ClinicalSourceKind;
  entityType?: string;
  fromDate?: string;
  toDate?: string;
  cursor?: string;
};

export class ClinicalSearchApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";


export const clinicianRole = clinicalRole;

function parameters(filters: ClinicalSearchFilters): URLSearchParams {
  const query = new URLSearchParams({
    purpose: "treatment",
    patient_id: filters.patientId,
  });
  if (filters.q) query.set("q", filters.q);
  if (filters.sourceKind) query.set("source_kind", filters.sourceKind);
  if (filters.entityType) query.set("entity_type", filters.entityType);
  if (filters.fromDate) query.set("from", `${filters.fromDate}T00:00:00Z`);
  if (filters.toDate) query.set("to", `${filters.toDate}T23:59:59.999Z`);
  if (filters.cursor) query.set("cursor", filters.cursor);
  return query;
}

async function errorFrom(response: Response, fallback: string): Promise<ClinicalSearchApiError> {
  const payload = (await response.json().catch(() => null)) as {
    detail?: string;
  } | null;
  return new ClinicalSearchApiError(payload?.detail ?? fallback, response.status);
}

export async function searchClinicalRecords(
  filters: ClinicalSearchFilters,
): Promise<ClinicalSearchResponse> {
  const query = parameters(filters);
  query.set("page_size", "20");
  const response = await fetch(`${apiUrl}/api/v1/clinical-search?${query}`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${await clinicalAccessToken()}` },
  });
  if (!response.ok) {
    throw await errorFrom(response, "Reviewed-record search is unavailable.");
  }
  return response.json() as Promise<ClinicalSearchResponse>;
}

export async function getClinicalTimeline(
  filters: ClinicalSearchFilters,
): Promise<LongitudinalTimeline> {
  const query = parameters(filters);
  query.delete("patient_id");
  query.delete("q");
  query.delete("entity_type");
  query.delete("cursor");
  const response = await fetch(
    `${apiUrl}/api/v1/clinical-search/timeline/${encodeURIComponent(filters.patientId)}?${query}`,
    {
      cache: "no-store",
      headers: { Authorization: `Bearer ${await clinicalAccessToken()}` },
    },
  );
  if (!response.ok) {
    throw await errorFrom(response, "Longitudinal timeline is unavailable.");
  }
  return response.json() as Promise<LongitudinalTimeline>;
}

export async function downloadClinicalSearchCsv(
  filters: ClinicalSearchFilters,
): Promise<void> {
  const query = parameters(filters);
  query.delete("cursor");
  const response = await fetch(`${apiUrl}/api/v1/clinical-search/export.csv?${query}`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${await clinicalAccessToken()}` },
  });
  if (!response.ok) {
    throw await errorFrom(response, "Clinical export is unavailable.");
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "medikiosk-clinical-search.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}
