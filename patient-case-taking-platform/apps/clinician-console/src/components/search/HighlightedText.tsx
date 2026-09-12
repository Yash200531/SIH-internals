export function HighlightedText({ fragment }: { fragment: string }) {
  const parts = fragment.split(/(<mark>.*?<\/mark>)/g);
  return (
    <>
      {parts.map((part, index) => part.startsWith("<mark>") && part.endsWith("</mark>")
        ? <mark key={`${index}-${part}`}>{part.slice(6, -7)}</mark>
        : <span key={`${index}-${part}`}>{part}</span>)}
    </>
  );
}
