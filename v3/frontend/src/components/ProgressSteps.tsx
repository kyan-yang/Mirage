import type { StepInfo } from "../App";

interface ProgressStepsProps {
  steps: Record<string, StepInfo>;
}

const STEP_LABELS: { key: string; label: string }[] = [
  { key: "expand", label: "Expanding prompt with Gemini" },
  { key: "video", label: "Generating video with Veo 3.1" },
  { key: "world", label: "Building 3D world with HunyuanWorld-Mirror" },
];

export default function ProgressSteps({ steps }: ProgressStepsProps) {
  return (
    <div className="progress active">
      {STEP_LABELS.map((s, i) => {
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
