"use client";

import Link from "next/link";
import { useState } from "react";
import { commandAlert, listAlerts, type ClinicalAlert } from "../../lib/summaryWorkflow";

export default function AlertsPage() {
  const [items, setItems] = useState<ClinicalAlert[]>([]);
  const [purpose, setPurpose] = useState(false);
  const [closed, setClosed] = useState(false);
  const [selected, setSelected] = useState<ClinicalAlert | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    setBusy(true); setSelected(null); setMessage("Loading alert queue…");
    try { const rows = await listAlerts(closed); setItems(rows); setLoaded(true); setMessage("Queue refreshed. Reload to check for new alerts."); }
    catch (error) { setItems([]); setLoaded(false); setMessage(error instanceof Error ? error.message : "Alert queue unavailable. Follow local staff escalation procedures."); }
    finally { setBusy(false); }
  }
  async function act(action: "acknowledge" | "resolve") {
    if (!selected || !purpose) return;
    setBusy(true);
    try {
      const lifecycle = await commandAlert(selected, action, rationale);
      const updated = { ...selected, lifecycle };
      setSelected(updated); setItems(current => current.map(item => item.lifecycle.id === lifecycle.id ? updated : item));
      setRationale(""); setMessage(action === "acknowledge" ? "Acknowledged and ownership recorded. The concern remains open." : "Resolution recorded separately from note signing.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Command failed. Refresh before retrying."); }
    finally { setBusy(false); }
  }
  return <section className="alert-workspace" aria-busy={busy}>
    <header><h1>Clinical alerts</h1><p>Prototype deterministic flags for clinician review. No external staff notification is implied.</p><Link href="/login">Sign in to clinical access</Link></header>
    <label><input type="checkbox" checked={purpose} onChange={event => { setPurpose(event.target.checked); setItems([]); setSelected(null); setLoaded(false); }} /> I am accessing these alerts for treatment.</label>
    <label><input type="checkbox" checked={closed} disabled={busy} onChange={event => setClosed(event.target.checked)} /> Include resolved alerts</label>
    <button className="alert-button" onClick={load} disabled={!purpose || busy}>Refresh alert queue</button>
    <p role="status" aria-live="polite">{message}</p>
    {loaded && items.length === 0 && <p>No alerts in this view. This does not establish that an encounter is safe or routine.</p>}
    <div className="alert-grid"><div>{items.map(item => <button className="alert-card" key={item.lifecycle.id} disabled={busy} onClick={() => { setSelected(item); setRationale(""); }}>
      <strong>{item.rule.severity.toUpperCase()} · {item.lifecycle.state}</strong><p>{item.rule.explanation_code.replaceAll("_", " ")}</p><small>Encounter {item.lifecycle.encounter_id}</small>
    </button>)}</div>
    {selected && <article className="alert-card"><h2>Alert review</h2><p>Event delivery: <strong>{selected.delivery === "broker_published" ? "Published to broker" : selected.delivery}</strong>. This is separate from staff receipt.</p>{selected.delivery === "failed" && <p role="alert">Event delivery needs operator attention. Contact staff directly; the concern remains in this queue.</p>}
      <p>State: <strong>{selected.lifecycle.state}</strong> · Owner role: {selected.lifecycle.owner_role}</p>
      <p>Owner: {selected.lifecycle.owner_actor_id || "Awaiting acknowledgement"}</p>
      <p>Last update: {new Date(selected.lifecycle.updated_at).toLocaleString()}</p>
      <p>Rule: {selected.rule.rule_id} · {selected.rule.approval_status.replaceAll("_", " ")}</p>
      <h3>Confirmed source fields</h3><ul>{selected.rule.evidence_paths.map(path => <li key={path}>{path.replaceAll("_", " ")}</li>)}</ul>
      <Link href={`/doctor?encounter_id=${selected.lifecycle.encounter_id}`}>Open encounter review</Link>
      {(selected.lifecycle.state === "open" || selected.lifecycle.state === "escalated") && <button className="alert-button" disabled={busy || !purpose} onClick={() => act("acknowledge")}>Acknowledge and take ownership</button>}
      {selected.lifecycle.state === "acknowledged" && <div><p>Resolution requires the owning doctor and a clinical assessment. Acknowledgement alone does not resolve the concern.</p><label>Assessment rationale<textarea value={rationale} maxLength={2000} onChange={event => setRationale(event.target.value)} /></label><button className="alert-button" disabled={busy || !purpose || !rationale.trim()} onClick={() => act("resolve")}>Record resolution</button></div>}
    </article>}</div>
  </section>;
}
