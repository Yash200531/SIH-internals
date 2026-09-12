"use client";

import { FormEvent, useEffect, useState } from "react";
import { SearchResults } from "@/components/search/SearchResults";
import { TimelineView } from "@/components/search/TimelineView";
import {
  ClinicalSearchApiError,
  type ClinicalSearchFilters,
  type ClinicalSearchResponse,
  type ClinicalSourceKind,
  type LongitudinalTimeline,
  clinicianRole,
  downloadClinicalSearchCsv,
  getClinicalTimeline,
  searchClinicalRecords,
} from "@/lib/clinicalSearch";

type View = "relevance" | "timeline";

export default function ClinicalSearchPage() {
  const [patientId, setPatientId] = useState("");
  const [query, setQuery] = useState("");
  const [sourceKind, setSourceKind] = useState<ClinicalSourceKind | "">("");
  const [entityType, setEntityType] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [purposeConfirmed, setPurposeConfirmed] = useState(false);
  const [view, setView] = useState<View>("relevance");
  const [result, setResult] = useState<ClinicalSearchResponse | null>(null);
  const [timeline, setTimeline] = useState<LongitudinalTimeline | null>(null);
  const [role, setRole] = useState<"doctor" | "nurse" | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // Session storage is browser-only. Defer the read so the server and first
    // client render stay identical and cannot produce a hydration mismatch.
    queueMicrotask(() => setRole(clinicianRole()));
  }, []);

  function filters(cursor?: string): ClinicalSearchFilters {
    return {
      patientId: patientId.trim(),
      q: query.trim() || undefined,
      sourceKind: sourceKind || undefined,
      entityType: entityType || undefined,
      fromDate: fromDate || undefined,
      toDate: toDate || undefined,
      cursor,
    };
  }

  async function run(nextView: View, cursor?: string) {
    if (!patientId.trim()) {
      setError("Enter the patient UUID before opening reviewed clinical records.");
      return;
    }
    if (!purposeConfirmed) {
      setError("Confirm treatment purpose before opening reviewed clinical records.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (nextView === "timeline") {
        setTimeline(await getClinicalTimeline(filters()));
      } else {
        const next = await searchClinicalRecords(filters(cursor));
        setResult((current) => cursor && current
          ? { ...next, hits: [...current.hits, ...next.hits] }
          : next);
      }
      setView(nextView);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Clinical retrieval is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(view);
  }

  async function exportCsv() {
    setExporting(true);
    setError("");
    try {
      await downloadClinicalSearchCsv(filters());
    } catch (caught) {
      const message = caught instanceof ClinicalSearchApiError
        ? caught.message
        : "Clinical export is unavailable.";
      setError(message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="clinical-search-page">
      <header className="dashboard-heading">
        <div>
          <span className="mk-eyebrow">Reviewed evidence · treatment access audited</span>
          <h1 className="mk-display">Clinical search</h1>
          <p>Search clinician-signed summaries and reviewed document facts across authorized facilities.</p>
        </div>
        <span className="mk-pill mk-pill--success">Human-reviewed sources only</span>
      </header>

      <form className="mk-card search-form" onSubmit={submit}>
        <div className="search-primary-fields">
          <label htmlFor="search-patient">Patient UUID <span aria-hidden="true">*</span></label>
          <input id="search-patient" value={patientId} onChange={(event) => setPatientId(event.target.value)}
            placeholder="33333333-3333-4333-8333-333333333333" required />
          <label htmlFor="search-query">Clinical terms</label>
          <input id="search-query" type="search" value={query} maxLength={200}
            onChange={(event) => setQuery(event.target.value)} placeholder="e.g. heart attack, metformin" />
        </div>
        <details className="search-filter-disclosure">
          <summary>Source and date filters</summary>
          <div className="search-filter-grid">
            <label htmlFor="search-source">Source</label>
            <select id="search-source" value={sourceKind}
              onChange={(event) => setSourceKind(event.target.value as ClinicalSourceKind | "")}>
              <option value="">All reviewed sources</option>
              <option value="signed_summary">Signed summaries</option>
              <option value="reviewed_fact">Reviewed document facts</option>
            </select>
            <label htmlFor="search-entity">Fact type</label>
            <select id="search-entity" value={entityType} onChange={(event) => setEntityType(event.target.value)}>
              <option value="">All fact types</option>
              <option value="medication_statement">Medication statement</option>
              <option value="diagnosis_statement">Diagnosis statement</option>
              <option value="lab_result">Lab result</option>
              <option value="allergy_statement">Allergy statement</option>
            </select>
            <label htmlFor="search-from">From date</label>
            <input id="search-from" type="date" value={fromDate} max={toDate || undefined}
              onChange={(event) => setFromDate(event.target.value)} />
            <label htmlFor="search-to">To date</label>
            <input id="search-to" type="date" value={toDate} min={fromDate || undefined}
              onChange={(event) => setToDate(event.target.value)} />
          </div>
        </details>
        <label className="purpose-check">
          <input type="checkbox" checked={purposeConfirmed}
            onChange={(event) => setPurposeConfirmed(event.target.checked)} />
          <span><strong>Treatment purpose</strong>I am opening this patient’s reviewed record to provide care. This access is audited.</span>
        </label>
        <div className="search-actions">
          <div className="view-switch" aria-label="Result ordering">
            <button type="button" aria-pressed={view === "relevance"}
              onClick={() => void run("relevance")}>Best match</button>
            <button type="button" aria-pressed={view === "timeline"}
              onClick={() => void run("timeline")}>Chronological timeline</button>
          </div>
          <button className="mk-button mk-button--primary" type="submit" disabled={loading}>
            {loading ? "Retrieving…" : view === "timeline" ? "Open timeline" : "Search reviewed records"}
          </button>
        </div>
      </form>

      {error && <div className="search-error" role="alert"><strong>Records could not be opened.</strong><p>{error}</p></div>}
      {loading && <div className="search-loading" role="status" aria-live="polite" aria-busy="true">Checking authorized reviewed records…</div>}

      {!loading && view === "relevance" && result && (
        <section className="search-output" aria-labelledby="search-results-title">
          <header>
            <div><span className="mk-eyebrow">Search result</span><h2 id="search-results-title">{result.total} reviewed record{result.total === 1 ? "" : "s"}</h2><p>{result.took_ms} ms · Results are filtered to this patient and your authorized facilities.</p></div>
            {role === "doctor" ? (
              <button className="mk-button mk-button--soft" type="button" disabled={exporting}
                onClick={() => void exportCsv()}>{exporting ? "Preparing…" : "Export private CSV"}</button>
            ) : role === "nurse" ? <span className="export-policy">CSV export is doctor-only.</span> : null}
          </header>
          {(Object.keys(result.facets.source_kinds).length > 0 || Object.keys(result.facets.entity_types).length > 0) && (
            <div className="search-facets" aria-label="Result breakdown">
              {Object.entries({ ...result.facets.source_kinds, ...result.facets.entity_types }).map(([name, count]) => (
                <span key={name}>{name.replaceAll("_", " ")} <strong>{count}</strong></span>
              ))}
            </div>
          )}
          <SearchResults result={result} />
          {result.next_cursor && <button className="mk-button mk-button--soft load-more" type="button"
            onClick={() => void run("relevance", result.next_cursor ?? undefined)}>Load more reviewed records</button>}
        </section>
      )}

      {!loading && view === "timeline" && timeline && (
        <section className="search-output" aria-labelledby="timeline-title">
          <header><div><span className="mk-eyebrow">Longitudinal context</span><h2 id="timeline-title">{timeline.summary.total_events} events across {timeline.summary.encounter_count} encounters</h2><p>{timeline.summary.signed_summary_count} signed summaries · {timeline.summary.reviewed_fact_count} reviewed facts</p></div></header>
          <TimelineView timeline={timeline} />
        </section>
      )}
    </div>
  );
}
