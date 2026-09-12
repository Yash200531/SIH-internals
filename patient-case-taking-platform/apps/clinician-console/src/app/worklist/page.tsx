"use client";

import Link from "next/link";
import { useState } from "react";
import { evaluateIntakeAlerts, confirmIntake, generateIntakeSummary, listIntakes, listSummaries,
  type IntakeHandoff } from "../../lib/summaryWorkflow";

export default function WorklistPage() {
  const [items, setItems] = useState<IntakeHandoff[]>([]);
  const [selected, setSelected] = useState<IntakeHandoff | null>(null);
  const [purpose, setPurpose] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState("Confirm treatment purpose to open accepted patient intakes.");
  const [handoff, setHandoff] = useState<string | null>(null);

  async function load(nextOffset = 0) {
    setBusy(true); setSelected(null); setReviewed(false); setHandoff(null);
    setMessage("Loading accepted intakes…");
    try {
      const records = await listIntakes(nextOffset);
      setItems(records); setOffset(nextOffset); setLoaded(true);
      setMessage(`${records.length} accepted intakes loaded. Only active treatment consent is included.`);
    } catch (error) {
      setItems([]); setLoaded(false);
      setMessage(error instanceof Error ? error.message : "Unable to load intakes.");
    } finally { setBusy(false); }
  }

  async function checkAlerts() {
    if (!selected || !reviewed || !purpose) return;
    setBusy(true);
    try {
      const result = await evaluateIntakeAlerts(selected.id);
      setMessage(result.alerts.length ? `${result.alerts.length} durable alert(s) recorded. Open Alerts to acknowledge.` : "No configured flag matched. This does not establish that the patient is safe.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Alert evaluation failed. Contact nearby staff directly."); }
    finally { setBusy(false); }
  }

  async function prepare() {
    if (!selected || !reviewed || !purpose) return;
    setBusy(true); setMessage("Preparing clinician handoff…");
    try {
      const existing = await listSummaries(selected.encounter_id);
      let record = [...existing].reverse().find(item => item.status !== "superseded");
      if (!record) {
        const confirmed = await confirmIntake(selected);
        const updated = { ...selected, context_version: confirmed.version };
        setSelected(updated);
        setItems(current => current.map(item => item.id === updated.id ? updated : item));
        record = await generateIntakeSummary(updated);
      }
      setHandoff(record.encounter_id);
      setMessage(`Handoff ready: ${record.status.replace("_", " ")}. Open clinician review to continue.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Handoff failed. Reload and retry.");
    } finally { setBusy(false); }
  }

  return <div>
    <header className="dashboard-heading">
      <div><span className="mk-eyebrow">Clinical worklist</span>
        <h1 className="mk-display">From patient intake to clinician review.</h1>
        <p>Review the patient’s confirmed answers before preparing a clinical draft.</p></div>
      <Link className="mk-button mk-button--soft" href="/login">Clinical sign in</Link>
    </header>
    <section className="mk-card panel">
      <label><input type="checkbox" checked={purpose} disabled={busy} onChange={event => {
        setPurpose(event.target.checked); setItems([]); setSelected(null); setHandoff(null); setLoaded(false);
      }} /> I am accessing these records for treatment at my permitted facility.</label>
      <button className="mk-button mk-button--primary" disabled={!purpose || busy} onClick={() => load()}>Load worklist</button>
    </section>
    <p role="status" aria-live="polite" className="review-live-status">{message}</p>
    {loaded && items.length === 0 && <section className="mk-card panel"><h2>No accepted intakes on this page</h2>
      <p>Patient submissions appear after acceptance while treatment consent remains active.</p></section>}
    <div className="review-layout">
      <section className="mk-card panel" aria-label="Accepted intakes">
        {items.map(item => <article className="queue-row" key={item.id}>
          <div><strong>{item.chief_complaint}</strong><p>Patient {item.patient_id.slice(0, 8)} · {item.language.toUpperCase()}</p>
            <p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></p></div>
          <button className="filter-button" disabled={busy} aria-pressed={selected?.id === item.id} onClick={() => {
            setSelected(item); setReviewed(false); setHandoff(null);
          }}>Review intake</button>
        </article>)}
        {loaded && <nav aria-label="Worklist pages" className="filter-row">
          <button className="filter-button" disabled={busy || offset === 0} onClick={() => load(Math.max(0, offset - 50))}>Previous</button>
          <button className="filter-button" disabled={busy || items.length < 50} onClick={() => load(offset + 50)}>Next</button>
        </nav>}
      </section>
      {selected && <section className="mk-card panel" aria-label="Selected intake">
        <h2>{selected.chief_complaint}</h2><p>Patient-confirmed answers · clinician confirmation required</p>
        <dl>{Object.entries(selected.confirmed_answers).map(([question, answer]) => <div className="draft-section" key={question}>
          <dt><strong>{question.replaceAll("_", " ")}</strong></dt><dd>{answer}</dd>
        </div>)}</dl>
        <p>Encounter: {selected.encounter_id}</p>
        <label><input type="checkbox" checked={reviewed} disabled={busy} onChange={event => setReviewed(event.target.checked)} /> I reviewed these answers and confirm this intake for the clinical draft.</label>
        <button className="mk-button mk-button--primary" disabled={busy || !reviewed || !purpose} onClick={prepare}>Prepare handoff</button>
        <button className="mk-button mk-button--soft" disabled={busy || !reviewed || !purpose} onClick={checkAlerts}>Check confirmed intake for alerts</button>
        <Link className="mk-button mk-button--soft" href="/alerts">Open alert queue</Link>
        {handoff && <Link className="mk-button mk-button--soft" href={`/doctor?encounter_id=${encodeURIComponent(handoff)}`}>Open clinician review →</Link>}
      </section>}
    </div>
  </div>;
}
