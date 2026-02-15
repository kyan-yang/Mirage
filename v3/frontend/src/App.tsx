import { useState, useCallback, useRef } from "react";
import TabSelector from "./components/TabSelector";
import PromptInput from "./components/PromptInput";
import GenerateButton from "./components/GenerateButton";
import ProgressSteps from "./components/ProgressSteps";
import DebugPanel from "./components/DebugPanel";
import ResultViewer from "./components/ResultViewer";

const API_URL = import.meta.env.VITE_API_URL || "";

export type Category = "autonomous" | "humanoid";
export type StepState = "pending" | "active" | "done" | "error";

export interface StepInfo {
  state: StepState;
  detail: string;
}

export interface DebugData {
  originalPrompt: string;
  expandedPrompt: string;
  videoUrl: string;
  files: string[];
  runId: string;
}

export interface ResultData {
  runId: string;
  gaussiansPly: string;
}

export default function App() {
  const [category, setCategory] = useState<Category>("autonomous");
  const [prompt, setPrompt] = useState("");
  const [debugMode, setDebugMode] = useState(false);
  const [generating, setGenerating] = useState(false);

  const [steps, setSteps] = useState<Record<string, StepInfo>>({
    expand: { state: "pending", detail: "" },
    video: { state: "pending", detail: "" },
    world: { state: "pending", detail: "" },
  });
  const [showProgress, setShowProgress] = useState(false);

  const [debugData, setDebugData] = useState<DebugData>({
    originalPrompt: "",
    expandedPrompt: "",
    videoUrl: "",
    files: [],
    runId: "",
  });
  const [hasDebugData, setHasDebugData] = useState(false);

  const [result, setResult] = useState<ResultData | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  // Abort controller for cancelling in-flight generation
  const abortRef = useRef<AbortController | null>(null);

  const setStepState = useCallback(
    (step: string, state: StepState, detail?: string) => {
      setSteps((prev) => ({
        ...prev,
        [step]: { state, detail: detail ?? prev[step].detail },
      }));
    },
    []
  );

  const generate = useCallback(async () => {
    if (!prompt.trim() || generating) return;

    // Cancel any previous request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setGenerating(true);
    setShowProgress(true);
    setResult(null);
    setStreamError(null);
    setHasDebugData(false);
    setSteps({
      expand: { state: "pending", detail: "" },
      video: { state: "pending", detail: "" },
      world: { state: "pending", detail: "" },
    });
    setDebugData((prev) => ({ ...prev, originalPrompt: prompt }));

    try {
      const resp = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, category }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        throw new Error(
          `Server error: ${resp.status} ${resp.statusText}`
        );
      }

      if (!resp.body) {
        throw new Error("No response body — streaming not supported");
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              handleEvent(data);
            } catch {
              // ignore malformed SSE lines
            }
          }
        }
      }

      // Flush any remaining buffer
      if (buffer.startsWith("data: ")) {
        try {
          const data = JSON.parse(buffer.slice(6));
          handleEvent(data);
        } catch {
          // ignore
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;

      const message = (err as Error).message || "Connection failed";
      setStreamError(message);

      // Mark whichever step is currently active as errored
      setSteps((prev) => {
        const next = { ...prev };
        let foundActive = false;
        for (const key of ["expand", "video", "world"]) {
          if (next[key].state === "active") {
            next[key] = { state: "error", detail: message };
            foundActive = true;
          }
        }
        // If no step was active yet, mark expand as errored
        if (!foundActive) {
          next["expand"] = { state: "error", detail: message };
        }
        return next;
      });
    }

    setGenerating(false);
  }, [prompt, category, generating, setStepState]);

  function handleEvent(data: Record<string, unknown>) {
    const step = data.step as string;

    if (step === "expand_start") {
      setStepState("expand", "active");
    }
    if (step === "expand_done") {
      const expanded = (data.expanded_prompt as string) || "";
      setStepState(
        "expand",
        "done",
        expanded.slice(0, 120) + "..."
      );
      setDebugData((prev) => ({ ...prev, expandedPrompt: expanded }));
      setHasDebugData(true);
    }
    if (step === "video_start") {
      setStepState("video", "active");
    }
    if (step === "video_polling") {
      setStepState(
        "video",
        "active",
        `Generating... (${data.elapsed || 0}s)`
      );
    }
    if (step === "video_done") {
      const runId = data.run_id as string;
      setStepState("video", "done", "Video ready");
      setDebugData((prev) => ({
        ...prev,
        runId,
        videoUrl: `${API_URL}/runs/${runId}/file?path=generated_video.mp4`,
      }));
    }
    if (step === "world_start") {
      setStepState("world", "active");
    }
    if (step === "world_done") {
      setStepState("world", "done");
      const runId = data.run_id as string;
      const files = (data.files as string[]) || [];
      const gaussiansPly =
        (data.gaussians_ply as string) || "gaussians.ply";
      setDebugData((prev) => ({ ...prev, runId, files }));
      setResult({ runId, gaussiansPly });
      setStreamError(null);
    }
    if (step === "error") {
      const message = (data.message as string) || "Failed";
      setStreamError(message);
      setSteps((prev) => {
        const next = { ...prev };
        for (const key of ["expand", "video", "world"]) {
          if (next[key].state === "active") {
            next[key] = { state: "error", detail: message };
          }
        }
        return next;
      });
    }
  }

  const handleRetry = useCallback(() => {
    setStreamError(null);
    // Re-trigger generation (will reset all state)
    generate();
  }, [generate]);

  const hasOutput = showProgress || result;

  return (
    <div className="layout">
      <div className="pane pane-left">
        <div className="pane-left-inner">
          <div className="header">
            <h1>Synthetic Training Environments</h1>
            <p>
              Generate realistic training environments for autonomous vehicles and humanoid robots.
            </p>
          </div>
          <TabSelector category={category} onSelect={setCategory} />
          <PromptInput
            category={category}
            prompt={prompt}
            onPromptChange={setPrompt}
          />
          <GenerateButton
            generating={generating}
            disabled={!prompt.trim()}
            onClick={generate}
          />
        </div>
        <button
          className={`debug-toggle${debugMode ? " active" : ""}`}
          onClick={() => setDebugMode((d) => !d)}
        >
          Debug
        </button>
      </div>

      <div className="pane pane-right">
        {!hasOutput && (
          <div className="empty-state">
            <p>Describe a scenario and hit generate to build a 3D world.</p>
          </div>
        )}
        {showProgress && <ProgressSteps steps={steps} />}

        {/* Stream-level error with retry */}
        {streamError && !generating && (
          <div className="stream-error">
            <span className="error-icon">!</span>
            <span>{streamError}</span>
            <button className="retry-btn" onClick={handleRetry}>
              Retry
            </button>
          </div>
        )}

        {debugMode && hasDebugData && (
          <DebugPanel debugData={debugData} apiUrl={API_URL} />
        )}
        {result && <ResultViewer result={result} apiUrl={API_URL} />}
      </div>
    </div>
  );
}
