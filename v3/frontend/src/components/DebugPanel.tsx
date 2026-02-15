import type { DebugData } from "../App";

interface DebugPanelProps {
  debugData: DebugData;
  apiUrl: string;
}

interface FileCategories {
  [key: string]: string[];
}

function categorizeFiles(files: string[]): FileCategories {
  const categories: FileCategories = {
    "Final Outputs": [],
    "Depth Maps": [],
    "Normal Maps": [],
    "RGB Images": [],
    "Resized Images": [],
    "Input Frames": [],
    "Rendered Videos": [],
    "COLMAP Data": [],
    Other: [],
  };

  for (const file of files) {
    if (file.includes("gaussians.ply") || file === "generated_video.mp4") {
      categories["Final Outputs"].push(file);
    } else if (file.includes("depth/")) {
      categories["Depth Maps"].push(file);
    } else if (file.includes("normal/")) {
      categories["Normal Maps"].push(file);
    } else if (file.includes("images/") && !file.includes("resized")) {
      categories["RGB Images"].push(file);
    } else if (file.includes("images_resized/")) {
      categories["Resized Images"].push(file);
    } else if (file.includes("input_frames/")) {
      categories["Input Frames"].push(file);
    } else if (file.includes("rendered_")) {
      categories["Rendered Videos"].push(file);
    } else if (file.includes("sparse/")) {
      categories["COLMAP Data"].push(file);
    } else {
      categories["Other"].push(file);
    }
  }

  return categories;
}

export default function DebugPanel({ debugData, apiUrl }: DebugPanelProps) {
  const fileCategories = categorizeFiles(debugData.files);

  return (
    <div className="debug-section active">
      <div className="debug-panel">
        <h3>Original Prompt</h3>
        <div className="content">{debugData.originalPrompt}</div>
      </div>

      {debugData.expandedPrompt && (
        <div className="debug-panel">
          <h3>Expanded Prompt (Gemini)</h3>
          <div className="content">{debugData.expandedPrompt}</div>
        </div>
      )}

      {debugData.videoUrl && (
        <div className="debug-panel">
          <h3>Generated Video (Veo 3.1)</h3>
          <video src={debugData.videoUrl} controls />
        </div>
      )}

      {debugData.files.length > 0 && (
        <div className="debug-panel">
          <h3>World Generation Outputs</h3>
          {Object.entries(fileCategories).map(
            ([cat, files]) =>
              files.length > 0 && (
                <div className="file-category" key={cat}>
                  <h4>
                    {cat} ({files.length})
                  </h4>
                  <div className="file-grid">
                    {files.map((file) => (
                      <a
                        key={file}
                        href={`${apiUrl}/runs/${debugData.runId}/file?path=${encodeURIComponent(file)}`}
                        target="_blank"
                        rel="noreferrer"
                        className="file-item"
                      >
                        {file}
                      </a>
                    ))}
                  </div>
                </div>
              )
          )}
        </div>
      )}
    </div>
  );
}
