import { useEffect, useState, useCallback } from "react";
import type { ResultData } from "../App";
import SplatViewer from "./SplatViewer";

interface ResultViewerProps {
  result: ResultData;
  apiUrl: string;
}

export default function ResultViewer({ result, apiUrl }: ResultViewerProps) {
  const [plyData, setPlyData] = useState<Uint8Array | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const plyPath = result.gaussiansPly;
  const fileUrl = `${apiUrl}/runs/${result.runId}/file?path=${encodeURIComponent(plyPath)}`;
  const antimatterUrl = `https://antimatter15.com/splat/?url=${encodeURIComponent(fileUrl)}`;

  const fetchPly = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPlyData(null);

    const maxRetries = 10;
    const retryDelay = 2000;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const resp = await fetch(fileUrl);
        if (resp.status === 404 && attempt < maxRetries - 1) {
          // File not yet available on the volume — wait and retry
          await new Promise((r) => setTimeout(r, retryDelay));
          continue;
        }
        if (!resp.ok) {
          throw new Error(`Failed to fetch PLY (${resp.status} ${resp.statusText})`);
        }
        const buf = await resp.arrayBuffer();
        setPlyData(new Uint8Array(buf));
        setLoading(false);
        return;
      } catch (err) {
        if (attempt < maxRetries - 1) {
          await new Promise((r) => setTimeout(r, retryDelay));
          continue;
        }
        setError((err as Error).message || "Failed to load PLY file");
      }
    }

    setLoading(false);
  }, [fileUrl]);

  // Auto-fetch when result changes
  useEffect(() => {
    fetchPly();
  }, [fetchPly]);

  return (
    <div className="result active">
      <div className="splat-container">
        {loading && (
          <div className="splat-fetch-loading">
            <span className="spinner" />
            <span>Downloading 3D model...</span>
          </div>
        )}

        {error && (
          <div className="splat-fetch-error">
            <span className="error-icon">!</span>
            <span>{error}</span>
            <button className="retry-btn" onClick={fetchPly}>
              Retry
            </button>
          </div>
        )}

        {!loading && !error && (
          <SplatViewer fileData={plyData} fileName={plyPath} />
        )}
      </div>

      <div className="result-links">
        <a href={fileUrl}>Download PLY</a>
        <a href={antimatterUrl} target="_blank" rel="noreferrer">
          Open in antimatter15
        </a>
        <a
          href={`${apiUrl}/runs/${result.runId}`}
          target="_blank"
          rel="noreferrer"
        >
          All files
        </a>
      </div>
    </div>
  );
}
