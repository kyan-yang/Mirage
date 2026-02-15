import { useEffect, useState } from "react";
import SplatViewer from "./SplatViewer";

interface GalleryModalProps {
  item: {
    name: string;
    plyPath: string;
  };
  onClose: () => void;
}

export default function GalleryModal({ item, onClose }: GalleryModalProps) {
  const [plyData, setPlyData] = useState<Uint8Array | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);

      try {
        const resp = await fetch(item.plyPath);
        if (!resp.ok) {
          throw new Error(`Failed to load PLY (${resp.status})`);
        }
        const buf = await resp.arrayBuffer();
        if (cancelled) return;
        setPlyData(new Uint8Array(buf));
      } catch (err) {
        if (cancelled) return;
        setError((err as Error).message || "Failed to load model");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [item.plyPath]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="gallery-modal-overlay" onClick={onClose}>
      <div className="gallery-modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="gallery-modal-close" onClick={onClose}>
          ✕
        </button>

        <div className="gallery-modal-header">
          <h2>{item.name}</h2>
        </div>

        <div className="gallery-modal-viewer">
          {loading && (
            <div className="gallery-modal-loading">
              <span className="spinner" />
              <span>Loading 3D model...</span>
            </div>
          )}

          {error && (
            <div className="gallery-modal-error">
              <span className="error-icon">!</span>
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && plyData && (
            <SplatViewer fileData={plyData} fileName={item.name} />
          )}
        </div>

        <div className="gallery-modal-hint">
          Press ESC to close
        </div>
      </div>
    </div>
  );
}
