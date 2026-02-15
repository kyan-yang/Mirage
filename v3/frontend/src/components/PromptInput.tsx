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
    { label: "Snowy road with ice patches", prompt: "snowy road with ice patches" },
    { label: "Fallen tree blocking traffic", prompt: "road with fallen tree blocking traffic" },
    { label: "Flooded street with abandoned cars", prompt: "flooded suburban street with abandoned cars" },
    { label: "Highway construction zone", prompt: "construction zone on highway with cones and barriers" },
    { label: "Rainy city intersection at night", prompt: "city intersection at night with heavy rain" },
    { label: "Foggy mountain road", prompt: "foggy mountain road with reduced visibility" },
    { label: "Overturned truck on highway", prompt: "highway with overturned truck and debris" },
    { label: "Narrow bridge with oncoming traffic", prompt: "narrow bridge with oncoming traffic" },
  ],
  humanoid: [
    { label: "Dirty dishes piled in sink", prompt: "pile of dirty dishes in kitchen sink" },
    { label: "Laundry basket on the bed", prompt: "laundry basket full of clothes on bed" },
    { label: "Toys scattered across floor", prompt: "cluttered living room with toys scattered on floor" },
    { label: "Spilled groceries on counter", prompt: "kitchen counter with spilled groceries and bags" },
    { label: "Unmade bed with tangled sheets", prompt: "unmade bed with tangled sheets and pillows" },
    { label: "Dining table after a meal", prompt: "dining table with plates, cups, and food scraps" },
    { label: "Wet towels on bathroom floor", prompt: "bathroom with wet towels on floor" },
    { label: "Cluttered desk with tangled cables", prompt: "workspace desk with papers and cables tangled" },
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
