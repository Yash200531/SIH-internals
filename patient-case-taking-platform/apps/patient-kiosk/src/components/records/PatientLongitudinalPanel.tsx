import type {
  PatientLongitudinalTimeline,
  TimelineEntry,
} from "../../lib/patientPortal";

type Props = {
  language: "hi" | "en";
  timeline: PatientLongitudinalTimeline | null;
  fallback: TimelineEntry[];
  unavailable: boolean;
};

const COPY = {
  hi: {
    title: "आपकी स्वास्थ्य यात्रा",
    reviewed: "डॉक्टर द्वारा जाँची गई जानकारी",
    fallbackTitle: "सुरक्षित रिकॉर्ड अभी भी उपलब्ध हैं",
    fallbackHelp: "समयरेखा सेवा अभी उपलब्ध नहीं है। नीचे सीधे रिकॉर्ड से जाँची गई जानकारी दिखाई जा रही है।",
    empty: "अभी कोई हस्ताक्षरित रिपोर्ट या जाँची गई जानकारी नहीं है।",
    signed: "हस्ताक्षरित रिपोर्ट",
    fact: "जाँची गई जानकारी",
    encounters: "मुलाकातें",
  },
  en: {
    title: "Your health journey",
    reviewed: "Clinician-reviewed information",
    fallbackTitle: "Your direct records are still available",
    fallbackHelp: "The combined timeline is unavailable. Reviewed facts from the direct record are shown below.",
    empty: "No signed reports or reviewed facts are available yet.",
    signed: "Signed report",
    fact: "Reviewed fact",
    encounters: "encounters",
  },
};

function words(value: string): string {
  return value.replaceAll("_", " ");
}

export function PatientLongitudinalPanel({ language, timeline, fallback, unavailable }: Props) {
  const copy = COPY[language];
  const locale = language === "hi" ? "hi-IN" : "en-IN";
  return (
    <section className="mk-card p-6" aria-labelledby="longitudinal-heading">
      <p className="mk-eyebrow">{copy.reviewed}</p>
      <h2 id="longitudinal-heading" className="mk-display mt-2 text-3xl">{copy.title}</h2>

      {timeline && (
        <div className="mt-4 grid grid-cols-3 gap-2" aria-label="Timeline summary">
          <div className="rounded-xl bg-[var(--mk-surface-muted)] p-3"><strong className="block text-xl">{timeline.summary.signed_summary_count}</strong><span className="text-xs text-[var(--mk-ink-muted)]">{copy.signed}</span></div>
          <div className="rounded-xl bg-[var(--mk-surface-muted)] p-3"><strong className="block text-xl">{timeline.summary.reviewed_fact_count}</strong><span className="text-xs text-[var(--mk-ink-muted)]">{copy.fact}</span></div>
          <div className="rounded-xl bg-[var(--mk-surface-muted)] p-3"><strong className="block text-xl">{timeline.summary.encounter_count}</strong><span className="text-xs text-[var(--mk-ink-muted)]">{copy.encounters}</span></div>
        </div>
      )}

      {unavailable && (
        <div className="mt-4 rounded-xl border border-[var(--mk-warning)] bg-[var(--mk-warning-soft)] p-4" role="status">
          <strong>{copy.fallbackTitle}</strong>
          <p className="mt-1 text-sm text-[var(--mk-ink-muted)]">{copy.fallbackHelp}</p>
        </div>
      )}

      {timeline && timeline.events.length > 0 ? (
        <ol className="mt-5 space-y-4 border-l-2 border-[var(--mk-border)] pl-5">
          {timeline.events.map((event) => (
            <li className="relative" key={event.record_id}>
              <span className="absolute -left-[1.65rem] top-1 h-3 w-3 rounded-full bg-[var(--mk-brand)] ring-4 ring-white" aria-hidden="true" />
              <p className="text-xs font-bold text-[var(--mk-ink-muted)]"><time dateTime={event.occurred_at}>{new Date(event.occurred_at).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" })}</time> · {event.source_kind === "signed_summary" ? copy.signed : copy.fact}</p>
              <h3 className="mt-1 text-lg font-bold">{event.title}</h3>
              <ul className="mt-1 list-disc pl-5 text-sm text-[var(--mk-ink-muted)]">{event.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>
            </li>
          ))}
        </ol>
      ) : fallback.length > 0 ? (
        <ul className="mt-5 space-y-3">
          {fallback.map((item) => (
            <li key={item.id} className="rounded-xl bg-[var(--mk-surface-muted)] p-4">
              <p className="font-bold">{item.display_value}{item.unit ? ` ${item.unit}` : ""}</p>
              <p className="text-xs text-[var(--mk-ink-muted)]">{words(item.event_type)} · {words(item.statement_status)}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-5 rounded-xl bg-[var(--mk-surface-muted)] p-4 text-[var(--mk-ink-muted)]" role="status">{copy.empty}</p>
      )}
    </section>
  );
}
