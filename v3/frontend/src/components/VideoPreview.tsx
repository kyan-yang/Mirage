import { useRef, useEffect, useState, useCallback } from "react";

interface VideoPreviewProps {
  videoUrl: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

const MAX_RETRIES = 15;
const RETRY_INTERVAL_MS = 2000;

export default function VideoPreview({
  videoUrl,
  collapsed,
  onToggleCollapse,
}: VideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoReady, setVideoReady] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const checkVideoReady = useCallback(async () => {
    if (!videoUrl) return;

    // Cancel any previous check
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setVideoReady(false);
    setRetrying(true);
    setRetryCount(0);

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      if (controller.signal.aborted) return;

      try {
        const resp = await fetch(videoUrl, {
          method: "HEAD",
          signal: controller.signal,
        });
        if (resp.ok) {
          setVideoReady(true);
          setRetrying(false);
          return;
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
      }

      setRetryCount(attempt + 1);

      // Wait before retrying
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(resolve, RETRY_INTERVAL_MS);
        controller.signal.addEventListener("abort", () => {
          clearTimeout(timeout);
          resolve();
        });
      });
    }

    // Exhausted retries — show anyway and let the browser try
    if (!controller.signal.aborted) {
      setVideoReady(true);
      setRetrying(false);
    }
  }, [videoUrl]);

  // When video URL changes, start polling
  useEffect(() => {
    checkVideoReady();
    return () => {
      abortRef.current?.abort();
    };
  }, [checkVideoReady]);

  // Auto-play when video becomes ready
  useEffect(() => {
    if (videoRef.current && videoReady) {
      videoRef.current.load();
      videoRef.current.play().catch(() => {
        // Browser may block autoplay — that's fine, user can click play
      });
    }
  }, [videoReady]);

  return (
    <div className={`video-preview${collapsed ? " collapsed" : ""}`}>
      <button className="video-preview-header" onClick={onToggleCollapse}>
        <span className="video-preview-label">Generated Video</span>
        <span className="video-preview-toggle">
          {collapsed ? "Show" : "Hide"}
        </span>
      </button>

      {!collapsed && (
        <div className="video-preview-player">
          {retrying && !videoReady ? (
            <div className="video-loading">
              <span className="spinner" />
              <span>
                Waiting for video to be ready
                {retryCount > 0 && ` (${retryCount}/${MAX_RETRIES})`}...
              </span>
            </div>
          ) : (
            <video
              ref={videoRef}
              src={videoUrl}
              controls
              loop
              muted
              playsInline
            />
          )}
        </div>
      )}
    </div>
  );
}
