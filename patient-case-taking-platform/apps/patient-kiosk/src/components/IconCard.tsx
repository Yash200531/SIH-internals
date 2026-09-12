"use client";

interface IconCardProps {
  icon: string;
  label: string;
  selected?: boolean;
  onSelect: () => void;
  disabled?: boolean;
  size?: "medium" | "large";
}

export function IconCard({
  icon,
  label,
  selected = false,
  onSelect,
  disabled = false,
  size = "large",
}: IconCardProps) {
  const sizeClasses = size === "large"
    ? "w-[280px] h-[280px] text-[6rem]"
    : "w-[160px] h-[160px] text-[4rem]";

  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      aria-label={label}
      className={`
        ${sizeClasses}
        flex flex-col items-center justify-center gap-3
        rounded-3xl border-4 transition-all duration-150
        focus:outline-none focus:ring-4 focus:ring-accent/50
        select-none touch-manipulation
        ${selected
          ? "border-accent bg-accent/10 shadow-lg scale-[1.02]"
          : "border-gray-200 bg-white hover:border-primary/30 hover:shadow-md"
        }
        ${disabled ? "opacity-40 pointer-events-none" : "active:scale-[0.98]"}
      `}
    >
      <span aria-hidden="true" className="leading-none">{icon}</span>
      <span className={`text-lg font-semibold ${selected ? "text-accent" : "text-primary"} px-2 text-center`}>
        {label}
      </span>
    </button>
  );
}
