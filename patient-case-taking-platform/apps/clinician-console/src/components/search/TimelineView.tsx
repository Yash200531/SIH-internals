import type { LongitudinalTimeline } from "@/lib/clinicalSearch";

function label(value: string): string {
  return value.replaceAll("_", " ");
}

export function TimelineView({ timeline }: { timeline: LongitudinalTimeline }) {
  if (timeline.events.length === 0) {
    return (
      <div className="search-empty" role="status">
        <strong>No signed summaries or reviewed facts in this period.</strong>
        <p>The patient’s direct signed-report view remains available separately.</p>
      </div>
    );
  }
  return (
    <ol className="longitudinal-list" aria-label="Patient longitudinal timeline">
      {timeline.events.map((event) => (
        <li key={event.record_id}>
          <div className="timeline-marker" aria-hidden="true" />
          <article>
            <div className="timeline-date">
              <time dateTime={event.occurred_at}>
                {new Date(event.occurred_at).toLocaleDateString("en-IN", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                })}
              </time>
              <span>{label(event.source_kind)}</span>
            </div>
            <h2>{event.title}</h2>
            <ul>
              {event.details.map((detail) => <li key={detail}>{detail}</li>)}
            </ul>
            <p>Encounter {event.encounter_id.slice(0, 8)} · Facility {event.facility_id.slice(0, 8)}</p>
          </article>
        </li>
      ))}
    </ol>
  );
}
