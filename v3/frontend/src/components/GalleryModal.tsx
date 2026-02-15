import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { GalleryItem } from "./Gallery";
import SplatViewer from "./SplatViewer";

interface GalleryModalProps {
  item: GalleryItem;
  onClose: () => void;
}

function base64ToUint8Array(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export default function GalleryModal({ item, onClose }: GalleryModalProps) {
  const [plyData, setPlyData] = useState<Uint8Array | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    if (item.plyDataBase64) {
      try {
        const data = base64ToUint8Array(item.plyDataBase64);
        if (!cancelled) {
          setPlyData(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || "Failed to decode model");
        }
      }
      if (!cancelled) setLoading(false);
      return;
    }

    if (!item.plyPath) {
      setError("No model data");
      setLoading(false);
      return;
    }

    (async () => {
      setLoading(true);
      setError(null);

      try {
        const resp = await fetch(item.plyPath!);
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
  }, [item.plyPath, item.plyDataBase64]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return createPortal(
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
    </div>,
    document.body
  );
}
