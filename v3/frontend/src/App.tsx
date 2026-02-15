import { useState, useCallback, useRef, useEffect } from "react";
import TabSelector from "./components/TabSelector";
import PromptInput from "./components/PromptInput";
import ImageUpload from "./components/ImageUpload";
import GenerateButton from "./components/GenerateButton";
import ProgressSteps from "./components/ProgressSteps";
import type { StepLabel } from "./components/ProgressSteps";
import VideoPreview from "./components/VideoPreview";
import DebugPanel from "./components/DebugPanel";
import ResultViewer from "./components/ResultViewer";

const API_URL = import.meta.env.VITE_API_URL || "";
const CACHE_KEY = "scenario-gen-cache";

export type Category = "autonomous" | "humanoid";
export type InputMode = "text" | "upload";
export type StepState = "pending" | "active" | "done" | "error";

const TEXT_STEP_LABELS: StepLabel[] = [
  { key: "expand", label: "Expanding prompt with Gemini" },
  { key: "video", label: "Generating video with Veo 3.1" },
  { key: "world", label: "Building 3D world with HunyuanWorld-Mirror" },
];

const UPLOAD_STEP_LABELS: StepLabel[] = [
  { key: "upload", label: "Processing uploaded files" },
  { key: "world", label: "Building 3D world with HunyuanWorld-Mirror" },
];

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

interface CachedState {
  steps: Record<string, StepInfo>;
  showProgress: boolean;
  debugData: DebugData;
  hasDebugData: boolean;
  result: ResultData | null;
  videoCollapsed: boolean;
}

function loadCache(): CachedState | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as CachedState;
  } catch {
    return null;
  }
}

function saveCache(state: CachedState) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(state));
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export default function App() {
  const cached = useRef(loadCache());

  const [inputMode, setInputMode] = useState<InputMode>("text");
  const [category, setCategory] = useState<Category>("autonomous");
  const [prompt, setPrompt] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [debugMode, setDebugMode] = useState(false);
  const [generating, setGenerating] = useState(false);

  const [steps, setSteps] = useState<Record<string, StepInfo>>(
    cached.current?.steps ?? {
      expand: { state: "pending", detail: "" },
      video: { state: "pending", detail: "" },
      world: { state: "pending", detail: "" },
    }
  );
  const [showProgress, setShowProgress] = useState(cached.current?.showProgress ?? false);

  const [debugData, setDebugData] = useState<DebugData>(
    cached.current?.debugData ?? {
      originalPrompt: "",
      expandedPrompt: "",
      videoUrl: "",
      files: [],
      runId: "",
    }
  );
  const [hasDebugData, setHasDebugData] = useState(cached.current?.hasDebugData ?? false);

  const [result, setResult] = useState<ResultData | null>(cached.current?.result ?? null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [videoCollapsed, setVideoCollapsed] = useState(cached.current?.videoCollapsed ?? false);

  // Abort controller for cancelling in-flight generation
  const abortRef = useRef<AbortController | null>(null);

  // Persist key state to localStorage whenever it changes
  useEffect(() => {
    saveCache({ steps, showProgress, debugData, hasDebugData, result, videoCollapsed });
  }, [steps, showProgress, debugData, hasDebugData, result, videoCollapsed]);

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
    if (inputMode === "text" && !prompt.trim()) return;
    if (inputMode === "upload" && uploadFiles.length === 0) return;
    if (generating) return;

    // Cancel any previous request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setGenerating(true);
    setShowProgress(true);
    setResult(null);
    setStreamError(null);
    setHasDebugData(false);
    setVideoCollapsed(false);

    // Clear previous debug data (including video URL) so the old video doesn't linger
    const freshDebug: DebugData = {
      originalPrompt: "",
      expandedPrompt: "",
      videoUrl: "",
      files: [],
      runId: "",
    };

    if (inputMode === "upload") {
      setSteps({
        upload: { state: "active", detail: "" },
        world: { state: "pending", detail: "" },
      });
      setDebugData(freshDebug);
    } else {
      setSteps({
        expand: { state: "pending", detail: "" },
        video: { state: "pending", detail: "" },
        world: { state: "pending", detail: "" },
      });
      setDebugData({ ...freshDebug, originalPrompt: prompt });
    }

    try {
      let resp: Response;

      if (inputMode === "upload") {
        const formData = new FormData();
        uploadFiles.forEach((f) => formData.append("files", f));
        resp = await fetch(`${API_URL}/upload`, {
          method: "POST",
          body: formData,
          signal: controller.signal,
        });
      } else {
        resp = await fetch(`${API_URL}/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, category }),
          signal: controller.signal,
        });
      }

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
        for (const key of Object.keys(next)) {
          if (next[key].state === "active") {
            next[key] = { state: "error", detail: message };
            foundActive = true;
          }
        }
        // If no step was active yet, mark the first step as errored
        if (!foundActive) {
          const firstKey = Object.keys(next)[0];
          if (firstKey) next[firstKey] = { state: "error", detail: message };
        }
        return next;
      });
    }

    setGenerating(false);
  }, [prompt, category, inputMode, uploadFiles, generating, setStepState]);

  function handleEvent(data: Record<string, unknown>) {
    const step = data.step as string;

    if (step === "upload_done") {
      const fileCount = (data.file_count as number) || 0;
      setStepState("upload", "done", `${fileCount} file${fileCount !== 1 ? "s" : ""} ready`);
      setDebugData((prev) => ({ ...prev, runId: (data.run_id as string) || "" }));
      setHasDebugData(true);
    }
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
      // Auto-collapse video preview so the 3D viewer gets focus
      setVideoCollapsed(true);
    }
    if (step === "error") {
      const message = (data.message as string) || "Failed";
      setStreamError(message);
      setSteps((prev) => {
        const next = { ...prev };
        for (const key of Object.keys(next)) {
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

  const handleNewChat = useCallback(() => {
    // Abort any in-flight generation
    abortRef.current?.abort();
    abortRef.current = null;

    // Reset all state to initial values
    setInputMode("text");
    setCategory("autonomous");
    setPrompt("");
    setUploadFiles([]);
    setGenerating(false);
    setSteps({
      expand: { state: "pending", detail: "" },
      video: { state: "pending", detail: "" },
      world: { state: "pending", detail: "" },
    });
    setShowProgress(false);
    setDebugData({
      originalPrompt: "",
      expandedPrompt: "",
      videoUrl: "",
      files: [],
      runId: "",
    });
    setHasDebugData(false);
    setResult(null);
    setStreamError(null);
    setVideoCollapsed(false);

    // Clear the cache so a reload also stays clean
    try { localStorage.removeItem(CACHE_KEY); } catch { /* ignore */ }
  }, []);

  const hasOutput = showProgress || result;

  return (
    <div className={`layout${!hasOutput ? " centered" : ""}`}>
      <div className="pane pane-left">
        <div className="pane-left-inner">
          <div className="header">
            <div className="header-row">
              <h1>Synthetic Training Environments</h1>
              {hasOutput && (
                <button className="new-chat-btn" onClick={handleNewChat}>
                  + New
                </button>
              )}
            </div>
            <p>
              Generate realistic training environments for autonomous vehicles and humanoid robots.
            </p>
          </div>
          <div className="mode-toggle">
            <button
              className={`mode-btn${inputMode === "text" ? " active" : ""}`}
              onClick={() => setInputMode("text")}
            >
              Text to 3D
            </button>
            <button
              className={`mode-btn${inputMode === "upload" ? " active" : ""}`}
              onClick={() => setInputMode("upload")}
            >
              Images to 3D
            </button>
          </div>

          {inputMode === "text" ? (
            <>
              <TabSelector category={category} onSelect={setCategory} />
              <PromptInput
                category={category}
                prompt={prompt}
                onPromptChange={setPrompt}
              />
            </>
          ) : (
            <ImageUpload files={uploadFiles} onFilesChange={setUploadFiles} />
          )}

          <GenerateButton
            generating={generating}
            disabled={
              inputMode === "text"
                ? !prompt.trim()
                : uploadFiles.length === 0
            }
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
        {showProgress && (
          <ProgressSteps
            steps={steps}
            stepLabels={inputMode === "upload" ? UPLOAD_STEP_LABELS : TEXT_STEP_LABELS}
          />
        )}

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

        {debugData.videoUrl && showProgress && (
          <VideoPreview
            videoUrl={debugData.videoUrl}
            collapsed={videoCollapsed}
            onToggleCollapse={() => setVideoCollapsed((c) => !c)}
          />
        )}

        {debugMode && hasDebugData && (
          <DebugPanel debugData={debugData} apiUrl={API_URL} />
        )}
        {result && <ResultViewer result={result} apiUrl={API_URL} />}
      </div>
    </div>
  );
}
