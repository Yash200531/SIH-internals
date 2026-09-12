"use client";

interface ProgressBarProps {
  currentStep: number;
  totalSteps: number;
  labels?: string[];
  showPercentage?: boolean;
}

export function ProgressBar({
  currentStep,
  totalSteps,
  labels,
  showPercentage = true,
}: ProgressBarProps) {
  const pct = Math.round((currentStep / totalSteps) * 100);

  return (
    <div className="w-full" role="progressbar" aria-valuenow={currentStep} aria-valuemin={0} aria-valuemax={totalSteps} aria-label={`Step ${currentStep} of ${totalSteps}`}>
      {labels && (
        <div className="flex justify-between mb-2">
          {labels.map((label, i) => (
            <span
              key={i}
              className={`text-xs font-medium ${
                i < currentStep ? "text-accent" : i === currentStep ? "text-primary" : "text-gray-400"
              }`}
            >
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="h-3 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="flex justify-between mt-2">
        <span className="text-sm text-gray-600">
          Step {currentStep} of {totalSteps}
        </span>
        {showPercentage && (
          <span className="text-sm font-semibold text-accent">{pct}%</span>
        )}
      </div>
    </div>
  );
}
