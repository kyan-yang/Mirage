import { useRef, useEffect } from "react";

interface VideoPreviewProps {
  videoUrl: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function VideoPreview({
  videoUrl,
  collapsed,
  onToggleCollapse,
}: VideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Auto-play when video URL becomes available
  useEffect(() => {
    if (videoRef.current && videoUrl) {
      videoRef.current.play().catch(() => {
        // Browser may block autoplay — that's fine, user can click play
      });
    }
  }, [videoUrl]);

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
          <video
            ref={videoRef}
            src={videoUrl}
            controls
            loop
            muted
            playsInline
          />
        </div>
      )}
    </div>
  );
}
