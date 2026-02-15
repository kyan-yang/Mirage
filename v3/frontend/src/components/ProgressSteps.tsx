import type { StepInfo } from "../App";

export interface StepLabel {
  key: string;
  label: string;
}

interface ProgressStepsProps {
  steps: Record<string, StepInfo>;
  stepLabels: StepLabel[];
}

export default function ProgressSteps({ steps, stepLabels }: ProgressStepsProps) {
  return (
    <div className="progress active">
      {stepLabels.map((s, i) => {
        const info = steps[s.key];
        return (
          <div key={s.key} className={`step ${info.state}`}>
            <div className="step-icon">
              {info.state === "active" ? (
                <span className="spinner" />
              ) : (
                i + 1
              )}
            </div>
            <div>
              <div className="step-text">{s.label}</div>
              {info.detail && (
                <div className="step-detail">{info.detail}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
