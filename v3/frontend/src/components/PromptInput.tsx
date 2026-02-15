import { useRef, useCallback } from "react";
import type { Category } from "../App";

interface PromptInputProps {
  category: Category;
  prompt: string;
  onPromptChange: (value: string) => void;
  files: File[];
  onFilesChange: (files: File[]) => void;
}

const EXAMPLES: Record<Category, { label: string; prompt: string }[]> = {
  autonomous: [
    { label: "Driving in the snow", prompt: "snowy road with falling snow and reduced traction" },
    { label: "Tree fallen in middle of road", prompt: "road blocked by a large fallen tree" },
    { label: "Heavy rain at night", prompt: "driving at night in heavy rain with low visibility" },
    { label: "Construction zone detour", prompt: "highway construction with cones and lane closures" },
    { label: "Foggy mountain road", prompt: "foggy mountain road with reduced visibility" },
    { label: "Deer crossing ahead", prompt: "country road with deer crossing warning signs" },
    { label: "Flooded street", prompt: "city street flooded with water covering the road" },
    { label: "Sharp curves ahead", prompt: "winding mountain road with sharp curves" },
  ],
  humanoid: [
    { label: "Cleaning up trash", prompt: "sidewalk with scattered trash and litter to clean" },
    { label: "Organizing scattered boxes", prompt: "warehouse with boxes scattered on the floor" },
    { label: "Picking up fallen items", prompt: "retail store with items fallen off shelves" },
    { label: "Clearing debris from path", prompt: "walkway with fallen branches and debris" },
    { label: "Sorting recycling bins", prompt: "area with mixed recycling materials to sort" },
    { label: "Tidying work area", prompt: "workspace with tools and materials scattered around" },
    { label: "Collecting scattered objects", prompt: "room with various objects scattered on the floor" },
    { label: "Straightening furniture", prompt: "room with displaced chairs and tables to arrange" },
  ],
};

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

export default function PromptInput({
  category,
  prompt,
  onPromptChange,
  files,
  onFilesChange,
}: PromptInputProps) {
  const examples = EXAMPLES[category];
  const placeholder =
    category === "autonomous"
      ? "Describe a driving scenario..."
      : "Describe a household scenario...";

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

  const removeFile = useCallback(
    (index: number) => {
      onFilesChange(files.filter((_, i) => i !== index));
    },
    [files, onFilesChange]
  );

  return (
    <div className="input-area">
      <div className="textarea-container">
        <textarea
          placeholder={placeholder}
          rows={3}
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
        />
        <button
          className="upload-icon-btn"
          onClick={() => inputRef.current?.click()}
          title="Upload reference images"
        >
          📎
        </button>
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
      </div>

      {files.length > 0 && (
        <div className="file-list-compact">
          {files.map((f, i) => (
            <div key={`${f.name}-${i}`} className="file-chip-compact">
              <span className="file-name">{f.name}</span>
              <span className="file-size">
                {f.size < 1024 * 1024
                  ? `${(f.size / 1024).toFixed(0)}kb`
                  : `${(f.size / (1024 * 1024)).toFixed(1)}mb`}
              </span>
              <button
                className="file-remove"
                onClick={() => removeFile(i)}
              >
                ×
              </button>
            </div>
          ))}
          <button className="clear-files-compact" onClick={() => onFilesChange([])}>
            Clear all
          </button>
        </div>
      )}

      <div className="examples">
        {examples.map((ex) => (
          <button key={ex.label} onClick={() => onPromptChange(ex.prompt)}>
            {ex.label}
          </button>
        ))}
      </div>
    </div>
  );
}
