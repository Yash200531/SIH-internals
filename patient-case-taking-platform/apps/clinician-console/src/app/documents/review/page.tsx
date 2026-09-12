"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";

import {
  addManualCandidate,
  decideCandidate,
  finalizeReview,
  getPagePreview,
  getReviewDocument,
  listReviewQueue,
  ReviewAction,
  ReviewCandidate,
  ReviewDocument,
  ReviewQueueItem,
} from "@/lib/documentReview";

const copy = {
  en: {
    eyebrow: "Document review · Source linked",
    title: "Verify every field against the page.",
    intro: "Nothing enters the clinical record until a nurse or doctor reviews it.",
    queue: "Review queue",
    source: "Source page",
    fields: "Extracted fields",
    unavailable: "Source preview unavailable. Acceptance is blocked; retry or defer.",
    verified: "I verified this field against the visible source",
    finalize: "Complete document review",
    manual: "Add field manually",
  },
  hi: {
    eyebrow: "दस्तावेज़ समीक्षा · स्रोत से जुड़ी",
    title: "हर जानकारी को पृष्ठ से मिलाएँ।",
    intro: "नर्स या डॉक्टर की समीक्षा के बिना कोई जानकारी रिकॉर्ड में नहीं जाएगी।",
    queue: "समीक्षा सूची",
    source: "मूल पृष्ठ",
    fields: "निकाली गई जानकारी",
    unavailable: "मूल पृष्ठ उपलब्ध नहीं है। स्वीकार न करें; दोबारा प्रयास करें या रोकें।",
    verified: "मैंने दिखाई दे रहे स्रोत से इस जानकारी की पुष्टि की है",
    finalize: "दस्तावेज़ समीक्षा पूरी करें",
    manual: "जानकारी स्वयं जोड़ें",
  },
};

const finalStates = new Set(["accepted", "corrected", "rejected"]);

function ageLabel(updatedAt: string) {
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(updatedAt).getTime()) / 60_000),
  );
  return minutes < 60 ? `${minutes} min waiting` : `${Math.floor(minutes / 60)} hr waiting`;
}

function CandidateCard({
  candidate,
  active,
  busy,
  onFocus,
  onDecision,
}: {
  candidate: ReviewCandidate;
  active: boolean;
  busy: boolean;
  onFocus: () => void;
  onDecision: (
    action: ReviewAction,
    verified: boolean,
    value?: string,
    unit?: string,
  ) => Promise<void>;
}) {
  const [verified, setVerified] = useState(false);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(candidate.normalized_value ?? "");
  const [unit, setUnit] = useState(candidate.unit ?? "");
  const resolved = finalStates.has(candidate.review_state);

  return (
    <article
      className="document-candidate"
      data-active={active}
      data-state={candidate.review_state}
      onFocus={onFocus}
    >
      <header>
        <div>
          <span className="candidate-kind">{candidate.entity_type.replaceAll("_", " ")}</span>
          <strong>{candidate.normalized_value ?? "No parsed value"} {candidate.unit}</strong>
        </div>
        <span className="candidate-state">{candidate.review_state.replaceAll("_", " ")}</span>
      </header>
      <p className="candidate-context">
        Page {candidate.source_page_number} · {candidate.temporality} · {candidate.subject}
        {candidate.negated ? " · negated" : ""}
      </p>
      {editing && !resolved ? (
        <div className="candidate-edit">
          <label>
            Corrected value
            <input value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
          <label>
            Unit
            <input value={unit} onChange={(event) => setUnit(event.target.value)} />
          </label>
        </div>
      ) : null}
      {!resolved ? (
        <>
          <label className="source-check">
            <input
              type="checkbox"
              checked={verified}
              onChange={(event) => setVerified(event.target.checked)}
            />
            I verified this field against the visible source / स्रोत से पुष्टि की
          </label>
          <div className="candidate-actions" aria-label="Review actions">
            <button disabled={busy || !verified} onClick={() => onDecision("accept", true)}>Accept</button>
            <button
              disabled={busy}
              onClick={() => {
                if (!editing) setEditing(true);
                else void onDecision("correct", verified, value, unit);
              }}
            >
              {editing ? "Save correction" : "Correct"}
            </button>
            <button disabled={busy} onClick={() => onDecision("reject", false)}>Reject</button>
            <button disabled={busy} onClick={() => onDecision("unreadable", false)}>Unreadable</button>
            <button disabled={busy} onClick={() => onDecision("request_rescan", false)}>Request rescan</button>
            <button disabled={busy} onClick={() => onDecision("defer", false)}>Defer</button>
          </div>
        </>
      ) : null}
    </article>
  );
}

export default function DocumentReviewPage() {
  const [language, setLanguage] = useState<"en" | "hi">("en");
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [document, setDocument] = useState<ReviewDocument | null>(null);
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(null);
  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [status, setStatus] = useState("Loading review queue…");
  const t = copy[language];

  const loadDocument = useCallback(async (documentId: string) => {
    setStatus("Loading document…");
    setPreviewError(false);
    try {
      const detail = await getReviewDocument(documentId);
      setDocument(detail);
      const first = detail.candidates[0];
      const firstPage = first
        ? detail.pages.find((page) => page.id === first.source_page_artifact_id)
        : detail.pages[0];
      setActiveCandidateId(first?.candidate_id ?? null);
      setActivePageId(firstPage?.id ?? null);
      if (firstPage) {
        try {
          const preview = await getPagePreview(documentId, firstPage.id);
          setPreviewUrl(preview.url);
        } catch {
          setPreviewUrl(null);
          setPreviewError(true);
        }
      }
      setStatus(`${detail.candidates.length} fields loaded`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Document review unavailable");
    }
  }, []);

  const loadQueue = useCallback(async () => {
    try {
      const items = await listReviewQueue();
      setQueue(items);
      setStatus(items.length ? `${items.length} documents need review` : "Review queue is clear");
      if (items[0]) await loadDocument(items[0].document_id);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Review queue unavailable");
    }
  }, [loadDocument]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadQueue(), 0);
    return () => window.clearTimeout(timer);
  }, [loadQueue]);

  const activeCandidate = useMemo(
    () => document?.candidates.find((item) => item.candidate_id === activeCandidateId) ?? null,
    [activeCandidateId, document],
  );
  const activePage = useMemo(
    () => document?.pages.find((page) => page.id === activePageId) ?? null,
    [activePageId, document],
  );
  const unresolved = document?.candidates.filter((item) => !finalStates.has(item.review_state)).length ?? 0;

  async function focusCandidate(candidate: ReviewCandidate) {
    setActiveCandidateId(candidate.candidate_id);
    setActivePageId(candidate.source_page_artifact_id);
    setPreviewError(false);
    try {
      const preview = await getPagePreview(document!.document_id, candidate.source_page_artifact_id);
      setPreviewUrl(preview.url);
    } catch {
      setPreviewUrl(null);
      setPreviewError(true);
    }
  }

  async function focusPage(pageId: string) {
    if (!document) return;
    setActivePageId(pageId);
    setActiveCandidateId(null);
    setPreviewError(false);
    try {
      const preview = await getPagePreview(document.document_id, pageId);
      setPreviewUrl(preview.url);
    } catch {
      setPreviewUrl(null);
      setPreviewError(true);
    }
  }

  async function reviewCandidate(
    candidate: ReviewCandidate,
    action: ReviewAction,
    verified: boolean,
    value?: string,
    unit?: string,
  ) {
    if (!document || ((action === "accept" || action === "correct") && previewError)) {
      setStatus(t.unavailable);
      return;
    }
    setBusyId(candidate.candidate_id);
    try {
      const updated = await decideCandidate(document.document_id, candidate.candidate_id, {
        action,
        expected_candidate_version: candidate.version,
        source_verified: verified,
        corrected_value: action === "correct" ? value : undefined,
        corrected_unit: action === "correct" ? unit || undefined : undefined,
        reason_code:
          action === "reject" ? "not_present" :
          action === "unreadable" ? "source_unreadable" :
          action === "request_rescan" ? "capture_quality" : undefined,
      });
      setDocument({
        ...document,
        candidates: document.candidates.map((item) =>
          item.candidate_id === updated.candidate_id ? updated : item,
        ),
      });
      setStatus(`${updated.entity_type.replaceAll("_", " ")} marked ${updated.review_state}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Review action failed");
    } finally {
      setBusyId(null);
    }
  }

  async function submitManual(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!document || !activePage || previewError) {
      setStatus(t.unavailable);
      return;
    }
    const form = new FormData(event.currentTarget);
    setBusyId("manual");
    try {
      const added = await addManualCandidate(document.document_id, {
        entity_type: String(form.get("entity_type")),
        normalized_value: String(form.get("normalized_value")),
        unit: String(form.get("unit") || "") || undefined,
        source_page_artifact_id: activePage.id,
        source_page_number: activePage.page_number,
        source_verified: true,
      });
      setDocument({ ...document, candidates: [...document.candidates, added] });
      setActiveCandidateId(added.candidate_id);
      event.currentTarget.reset();
      setStatus("Manual field added with source provenance");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Manual entry failed");
    } finally {
      setBusyId(null);
    }
  }

  async function completeReview() {
    if (!document || unresolved) return;
    setBusyId("finalize");
    try {
      const reviewed = await finalizeReview(document.document_id, document.version);
      setDocument(reviewed);
      setQueue((items) => items.filter((item) => item.document_id !== reviewed.document_id));
      setStatus("Review completed. Promotion is queued separately.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not complete review");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="document-review-page">
      <header className="dashboard-heading mk-enter">
        <div>
          <span className="mk-eyebrow">{t.eyebrow}</span>
          <h1 className="mk-display">{t.title}</h1>
          <p>{t.intro}</p>
        </div>
        <div className="review-toolbar">
          <button className="filter-button" onClick={() => setLanguage(language === "en" ? "hi" : "en")}>
            {language === "en" ? "हिन्दी" : "English"}
          </button>
          <button className="filter-button" onClick={() => void loadQueue()}>Refresh</button>
        </div>
      </header>

      <p className="review-live-status" role="status" aria-live="polite">{status}</p>

      <div className="document-review-grid mk-enter">
        <aside className="mk-card review-queue-panel" aria-label={t.queue}>
          <h2>{t.queue}</h2>
          {queue.map((item) => (
            <button
              key={item.document_id}
              className="review-queue-item"
              data-active={item.document_id === document?.document_id}
              onClick={() => void loadDocument(item.document_id)}
            >
              <strong>{item.document_class}</strong>
              <span>{item.unresolved_count} unresolved · {ageLabel(item.updated_at)}</span>
              <small>Patient …{item.patient_id.slice(-6)}</small>
            </button>
          ))}
          {!queue.length ? <p className="empty-review">No documents waiting / कोई दस्तावेज़ बाकी नहीं</p> : null}
        </aside>

        <section className="mk-card source-preview-panel" aria-label={t.source}>
          <header>
            <h2>{t.source}</h2>
            {document && document.pages.length > 1 ? (
              <select
                aria-label="Select source page"
                value={activePageId ?? ""}
                onChange={(event) => void focusPage(event.target.value)}
              >
                {document.pages.map((page) => <option key={page.id} value={page.id}>Page {page.page_number}</option>)}
              </select>
            ) : <span>Page {activePage?.page_number ?? "—"}</span>}
          </header>
          <div className="source-canvas">
            {previewUrl ? (
              <Image
                src={previewUrl}
                alt="Clinical document page for field verification"
                width={activePage?.width ?? 1200}
                height={activePage?.height ?? 1600}
                unoptimized
              />
            ) : null}
            {previewUrl && activeCandidate?.source_bbox && activeCandidate.source_page_width && activeCandidate.source_page_height ? (
              <span
                className="source-highlight"
                aria-label="Highlighted source region"
                style={{
                  left: `${activeCandidate.source_bbox[0] / activeCandidate.source_page_width * 100}%`,
                  top: `${activeCandidate.source_bbox[1] / activeCandidate.source_page_height * 100}%`,
                  width: `${(activeCandidate.source_bbox[2] - activeCandidate.source_bbox[0]) / activeCandidate.source_page_width * 100}%`,
                  height: `${(activeCandidate.source_bbox[3] - activeCandidate.source_bbox[1]) / activeCandidate.source_page_height * 100}%`,
                }}
              />
            ) : null}
            {previewError ? <div className="preview-error" role="alert"><strong>Preview unavailable</strong><p>{t.unavailable}</p><button onClick={() => activePage && void focusPage(activePage.id)}>Retry preview</button></div> : null}
          </div>
        </section>

        <section className="review-fields-panel" aria-label={t.fields}>
          <header className="review-fields-header">
            <div><h2>{t.fields}</h2><p>{unresolved} unresolved of {document?.candidates.length ?? 0}</p></div>
            <span className="mk-pill mk-pill--warning">Candidate · not clinical truth</span>
          </header>
          <div className="candidate-list">
            {document?.candidates.map((candidate) => (
              <CandidateCard
                key={`${candidate.candidate_id}:${candidate.version}`}
                candidate={candidate}
                active={candidate.candidate_id === activeCandidateId}
                busy={busyId === candidate.candidate_id}
                onFocus={() => void focusCandidate(candidate)}
                onDecision={(action, verified, value, unit) => reviewCandidate(candidate, action, verified, value, unit)}
              />
            ))}
          </div>
          {document && activePage ? (
            <form className="manual-entry" onSubmit={submitManual}>
              <h3>{t.manual}</h3>
              <select name="entity_type" aria-label="Field type" defaultValue="instructions">
                <option value="medication_statement">Medication</option><option value="strength">Strength</option>
                <option value="route">Route</option><option value="frequency">Frequency</option>
                <option value="duration">Duration</option><option value="instructions">Instructions</option>
              </select>
              <input name="normalized_value" aria-label="Field value" placeholder="Value" required />
              <input name="unit" aria-label="Unit, optional" placeholder="Unit (optional)" />
              <button disabled={busyId === "manual" || previewError}>Add verified field</button>
            </form>
          ) : null}
          <footer className="review-complete-bar">
            <div><strong>{unresolved ? `${unresolved} decisions remaining` : "Ready to complete"}</strong><span>Completion does not sign a clinical note.</span></div>
            <button className="mk-button mk-button--success" disabled={!document || unresolved > 0 || busyId === "finalize"} onClick={() => void completeReview()}>{t.finalize}</button>
          </footer>
        </section>
      </div>
    </div>
  );
}
