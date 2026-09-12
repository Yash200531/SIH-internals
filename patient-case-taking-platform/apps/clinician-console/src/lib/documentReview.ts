import { clinicalAccessToken } from "./clinicalSession";

export type ReviewState =
  | "unreviewed"
  | "accepted"
  | "corrected"
  | "rejected"
  | "unreadable"
  | "rescan_requested"
  | "deferred";

export type ReviewAction =
  | "accept"
  | "correct"
  | "reject"
  | "unreadable"
  | "request_rescan"
  | "defer";

export type ReviewQueueItem = {
  document_id: string;
  facility_id: string;
  patient_id: string;
  encounter_id: string;
  document_class: string;
  state: string;
  version: number;
  updated_at: string;
  candidate_count: number;
  unresolved_count: number;
};

export type ReviewCandidate = {
  candidate_id: string;
  entity_type: string;
  normalized_value: string | null;
  unit: string | null;
  source_page_artifact_id: string;
  source_ocr_artifact_id: string | null;
  source_region_id: string | null;
  source_page_number: number;
  parser_signal: string;
  negated: boolean;
  temporality: string;
  subject: string;
  uncertainty: string | null;
  document_statement: boolean;
  clinician_confirmed_current: boolean;
  review_state: ReviewState;
  version: number;
  source_page_width: number | null;
  source_page_height: number | null;
  source_bbox: [number, number, number, number] | null;
  source_polygon: [number, number][] | null;
};

export type ReviewDocument = {
  document_id: string;
  facility_id: string;
  patient_id: string;
  encounter_id: string;
  purpose: string;
  document_class: string;
  state: string;
  version: number;
  updated_at: string;
  candidates: ReviewCandidate[];
  pages: ReviewPage[];
};

export type ReviewPage = {
  id: string;
  page_number: number;
  width: number;
  height: number;
  preprocessing_version: string;
};

export class ReviewApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";


async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}/api/v1/document-reviews${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${await clinicalAccessToken()}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ReviewApiError(
      payload?.detail ?? "The document review service is unavailable.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export function listReviewQueue(): Promise<ReviewQueueItem[]> {
  return request<ReviewQueueItem[]>("");
}

export function getReviewDocument(documentId: string): Promise<ReviewDocument> {
  return request<ReviewDocument>(`/${documentId}`);
}

export function getPagePreview(
  documentId: string,
  pageArtifactId: string,
): Promise<{ url: string; expires_in_seconds: number }> {
  return request(`/${documentId}/pages/${pageArtifactId}/preview`);
}

export function decideCandidate(
  documentId: string,
  candidateId: string,
  body: {
    action: ReviewAction;
    expected_candidate_version: number;
    corrected_value?: string;
    corrected_unit?: string;
    reason_code?: string;
    source_verified: boolean;
  },
): Promise<ReviewCandidate> {
  return request(`/${documentId}/candidates/${candidateId}/decisions`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
}

export function addManualCandidate(
  documentId: string,
  body: {
    entity_type: string;
    normalized_value: string;
    unit?: string;
    source_page_artifact_id: string;
    source_page_number: number;
    source_verified: boolean;
  },
): Promise<ReviewCandidate> {
  return request(`/${documentId}/candidates`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
}

export function finalizeReview(
  documentId: string,
  expectedDocumentVersion: number,
): Promise<ReviewDocument> {
  return request(`/${documentId}/finalize`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      expected_document_version: expectedDocumentVersion,
    }),
  });
}
