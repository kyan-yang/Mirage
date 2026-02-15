import { useCallback, useRef, useState } from "react";

interface ImageUploadProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
}

const ACCEPTED_EXTENSIONS = new Set([
  ".jpg", ".jpeg", ".png", ".webp",
  ".mp4", ".mov", ".webm",
]);

function getExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function isVideoFile(f: File): boolean {
  return f.type.startsWith("video/") || [".mp4", ".mov", ".webm"].includes(getExtension(f.name));
}

export default function ImageUpload({ files, onFilesChange }: ImageUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const valid = Array.from(incoming).filter((f) =>
        ACCEPTED_EXTENSIONS.has(getExtension(f.name))
      );
      if (valid.length === 0) return;

      const hasVideo = valid.some(isVideoFile);
      const existingHasVideo = files.some(isVideoFile);

      if ((hasVideo && valid.length > 1) || (hasVideo && files.length > 0) || (existingHasVideo && valid.length > 0)) {
        // When video is involved, only allow a single video file
        const videoFile = valid.find(isVideoFile) ?? files.find(isVideoFile);
        if (videoFile) {
          onFilesChange([videoFile]);
        }
        return;
      }

      onFilesChange([...files, ...valid]);
    },
    [files, onFilesChange]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  const removeFile = useCallback(
    (index: number) => {
      onFilesChange(files.filter((_, i) => i !== index));
    },
    [files, onFilesChange]
  );

  return (
    <div className="upload-area">
      <div
        className={`drop-zone${dragOver ? " drag-over" : ""}${files.length > 0 ? " has-files" : ""}`}
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.webm"
          style={{ display: "none" }}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {files.length === 0 ? (
          <>
            <div className="drop-icon">&#8593;</div>
            <div className="drop-text">Drop images or video here</div>
            <div className="drop-hint">JPG, PNG, WebP &middot; MP4, MOV, WebM</div>
          </>
        ) : (
          <div className="drop-text">
            {files.length} file{files.length !== 1 ? "s" : ""} selected &mdash; click to add more
          </div>
        )}
      </div>

      {files.length > 0 && (
        <div className="file-list">
          {files.map((f, i) => (
            <div key={`${f.name}-${i}`} className="file-chip">
              <span className="file-name">{f.name}</span>
              <span className="file-size">
                {f.size < 1024 * 1024
                  ? `${(f.size / 1024).toFixed(0)}kb`
                  : `${(f.size / (1024 * 1024)).toFixed(1)}mb`}
              </span>
              <button
                className="file-remove"
                onClick={(e) => { e.stopPropagation(); removeFile(i); }}
              >
                &times;
              </button>
            </div>
          ))}
          <button className="clear-files" onClick={() => onFilesChange([])}>
            Clear all
          </button>
        </div>
      )}
    </div>
  );
}
