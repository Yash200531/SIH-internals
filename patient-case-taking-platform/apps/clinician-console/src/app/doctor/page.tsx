"use client";

import { Suspense, useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  listSummaries,
  regenerateSummary,
  rejectSummary,
  saveDraft,
  signSummary,
  submitForReview,
  type SummaryContent,
  type SummaryRecord,
} from "../../lib/summaryWorkflow";

type ListField = Exclude<keyof SummaryContent, "chief_complaint">;

const labels: Record<ListField, string> = {
  history_of_present_illness: "History of presenting concern",
  relevant_negatives: "Relevant negatives",
  document_facts: "Reviewed document facts",
  red_flags: "Deterministic warning flags",
  uncertainties: "Uncertainties and missing information",
};

export default function DoctorReviewPage() {
  return <Suspense fallback={<p role="status">Loading encounter…</p>}><DoctorReviewContent /></Suspense>;
}

function DoctorReviewContent() {
  const searchParams = useSearchParams();
  const [encounterId, setEncounterId] = useState(searchParams.get("encounter_id") ?? "");
  const [summaries, setSummaries] = useState<SummaryRecord[]>([]);
  const [selected, setSelected] = useState<SummaryRecord | null>(null);
  const [content, setContent] = useState<SummaryContent | null>(null);
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("Enter an encounter ID to load its summaries.");
  const [busy, setBusy] = useState(false);


  const choose = useCallback((summary: SummaryRecord) => {
    setSelected(summary);
    setContent(structuredClone(summary.content));
    setReason(summary.rejection_reason ?? "");
  }, []);

  async function load() {
    if (!encounterId.trim()) {
      setStatus("Encounter ID is required.");
      return;
    }
    setBusy(true);
    setStatus("Loading clinical summaries…");
    try {
      const records = await listSummaries(encounterId.trim());
      setSummaries(records);
      const current = [...records].reverse().find((item) => item.status !== "superseded");
      if (current) choose(current);
      else {
        setSelected(null);
        setContent(null);
      }
      setStatus(current
        ? `Loaded generation ${current.generation}, status ${current.status.replace("_", " ")}.`
        : "No summary draft exists for this encounter.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to load summaries.");
    } finally {
      setBusy(false);
    }
  }

  async function act(announcement: string, operation: () => Promise<SummaryRecord>) {
    setBusy(true);
    setStatus(`${announcement}…`);
    try {
      const updated = await operation();
      setSummaries((items) => [...items.filter((item) => item.id !== updated.id), updated]);
      choose(updated);
      setStatus(`${announcement} complete. Status: ${updated.status.replace("_", " ")}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : `${announcement} failed.`);
    } finally {
      setBusy(false);
    }
  }

  const editable = selected?.status === "draft" && !busy;
  const tone = selected?.status === "signed"
    ? "mk-pill--success"
    : selected?.status === "rejected" ? "mk-pill--danger" : "mk-pill--warning";

  return (
    <div>
      <header className="dashboard-heading mk-enter">
        <div>
          <span className="mk-eyebrow">Doctor review · Evidence linked</span>
          <h1 className="mk-display">Review before you sign.</h1>
          <p>Only clinician-confirmed intake, deterministic triage and reviewed document facts appear here.</p>
        </div>
        <span className={`mk-pill ${tone}`}>
          {selected ? `${selected.status.replace("_", " ")} · generation ${selected.generation}` : "No draft selected"}
        </span>
      </header>

      <section className="summary-loader mk-card" aria-label="Find encounter summary">
        <label htmlFor="encounter-id">Encounter ID</label>
        <input id="encounter-id" value={encounterId}
          onChange={(event) => setEncounterId(event.target.value)}
          placeholder="Paste the encounter UUID" />
        <button className="mk-button mk-button--primary" onClick={load} disabled={busy}>Load summary</button>
      </section>
      <p className="review-live-status" role="status" aria-live="polite">{status}</p>

      {!selected || !content ? (
        <section className="mk-card summary-empty">
          <h2>No clinical summary selected</h2>
          <p>Open the worklist to review an accepted patient intake and prepare a draft. Nothing is signed automatically.</p>
        </section>
      ) : (
        <div className="review-layout mk-enter">
          <aside className="mk-card patient-rail">
            {content.red_flags.length > 0 && <span className="mk-pill mk-pill--danger">Urgent flags present</span>}
            <h2 className="patient-name">Encounter summary</h2>
            <p className="patient-meta">Patient {selected.patient_id.slice(0, 8)}…</p>
            <div className="rail-list">
              <div className="rail-item"><span>Provider</span><strong>{selected.provider} {selected.degraded ? "· fallback" : "· offline"}</strong></div>
              <div className="rail-item"><span>Chief concern</span><strong>{content.chief_complaint}</strong></div>
              <div className="rail-item"><span>Version</span><strong>Generation {selected.generation} · edit {selected.lock_version}</strong></div>
              <div className="rail-item"><span>Review rule</span><strong>Clinician sign-off required</strong></div>
            </div>
            {summaries.length > 1 && <div className="summary-versions">
              <h3>Version history</h3>
              {summaries.map((item) => <button key={item.id} onClick={() => choose(item)}
                aria-pressed={item.id === selected.id}>Gen {item.generation} · {item.status.replace("_", " ")}</button>)}
            </div>}
          </aside>

          <section className="mk-card draft-panel">
            <header className="draft-header">
              <span className={`mk-pill ${tone}`}>{selected.status.replace("_", " ")} · {selected.provider}</span>
              <h2 className="mk-display">Clinical summary</h2>
              <p>{selected.status === "signed" ? "Signed and locked. Corrections require a future addendum workflow." : "This draft is not part of the signed record."}</p>
            </header>
            <div className="draft-body">
              <div className="draft-section">
                <label htmlFor="chief-complaint">Chief complaint</label>
                <textarea id="chief-complaint" disabled={!editable} value={content.chief_complaint}
                  onChange={(event) => setContent({ ...content, chief_complaint: event.target.value })} />
              </div>
              {(Object.keys(labels) as ListField[]).map((field) => <div className="draft-section" key={field}>
                <label htmlFor={field}>{labels[field]}</label>
                <textarea id={field} disabled={!editable || field === "red_flags"}
                  value={content[field].join("\n")}
                  onChange={(event) => setContent({ ...content,
                    [field]: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean),
                  })} />
                {field === "red_flags" && <span className="source-link">Safety flags are read-only and cannot be removed.</span>}
              </div>)}

              {selected.status !== "signed" && <div className="summary-reject">
                <label htmlFor="reject-reason">Rejection reason</label>
                <input id="reject-reason" value={reason} onChange={(event) => setReason(event.target.value)}
                  disabled={busy} />
              </div>}
              <div className="signoff">
                <div><strong>{selected.status === "signed" ? "Signed and locked" : "Clinician decision required"}</strong>
                  <p>{selected.status === "signed" ? "This version is immutable and available in the patient’s reports." : "Save edits, submit for review, then sign—or reject and regenerate a separate version."}</p></div>
                {selected.status !== "signed" && <div className="summary-actions">
                  <button className="mk-button mk-button--soft" disabled={!editable}
                    onClick={() => act("Saving draft", () => saveDraft(selected, content))}>Save draft</button>
                  <button className="mk-button mk-button--primary" disabled={!editable}
                    onClick={() => act("Submitting for review", () => submitForReview(selected))}>Submit review</button>
                  <button className="mk-button mk-button--danger"
                    disabled={busy || selected.status === "superseded" || !reason.trim()}
                    onClick={() => act("Rejecting draft", () => rejectSummary(selected, reason))}>Reject</button>
                  <button className="mk-button mk-button--soft"
                    disabled={busy || !["draft", "rejected"].includes(selected.status)}
                    onClick={() => act("Regenerating draft", () => regenerateSummary(selected))}>Regenerate</button>
                  <button className="mk-button mk-button--success" disabled={busy || selected.status !== "in_review"}
                    onClick={() => act("Signing summary", () => signSummary(selected))}>Sign & lock</button>
                </div>}
              </div>
            </div>
          </section>

          <aside className="mk-card evidence-rail">
            <h2>Source evidence</h2>
            {selected.evidence.length === 0 ? <p className="patient-meta">No evidence links were supplied. Review manually.</p>
              : selected.evidence.map((item, index) => <article className="evidence-card"
                key={`${item.output_path}-${index}`}><span>{item.source_type.replace("_", " ")}</span>
                <strong>{item.output_path.replaceAll("_", " ")}</strong><p>{item.source_path.replaceAll("_", " ")}</p></article>)}
            {content.uncertainties.map((item) => <article className="evidence-card" key={item}>
              <span>Unresolved</span><p>{item}</p></article>)}
          </aside>
        </div>
      )}
    </div>
  );
}
