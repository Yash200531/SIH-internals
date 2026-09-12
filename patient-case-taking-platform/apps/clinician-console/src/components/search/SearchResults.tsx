import type { ClinicalSearchResponse } from "@/lib/clinicalSearch";
import { HighlightedText } from "./HighlightedText";

function label(value: string): string {
  return value.replaceAll("_", " ");
}

export function SearchResults({ result }: { result: ClinicalSearchResponse }) {
  if (result.hits.length === 0) {
    return (
      <div className="search-empty" role="status">
        <strong>No reviewed records match these filters.</strong>
        <p>Try a broader date range or remove one filter. Unsigned drafts and raw OCR are never searched.</p>
      </div>
    );
  }
  return (
    <ol className="search-result-list" aria-label="Reviewed clinical search results">
      {result.hits.map((hit) => (
        <li className="search-result" key={hit.record_id}>
          <header>
            <div>
              <span className="mk-pill">{label(hit.source_kind)}</span>
              <h2>{hit.title}</h2>
            </div>
            <time dateTime={hit.occurred_at}>
              {new Date(hit.occurred_at).toLocaleString("en-IN", {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </time>
          </header>
          {hit.highlights.length > 0 && (
            <div className="search-highlights" aria-label="Matching excerpts">
              {hit.highlights.flatMap((highlight) =>
                highlight.fragments.map((fragment, index) => (
                  <p key={`${highlight.field}-${index}`}>
                    <span>{label(highlight.field)}</span>
                    <HighlightedText fragment={fragment} />
                  </p>
                )),
              )}
            </div>
          )}
          <footer>
            {hit.entity_type && <span>{label(hit.entity_type)}</span>}
            {hit.statement_status && <span>{label(hit.statement_status)}</span>}
            <span>Encounter {hit.encounter_id.slice(0, 8)}</span>
            <span>Facility {hit.facility_id.slice(0, 8)}</span>
          </footer>
        </li>
      ))}
    </ol>
  );
}
