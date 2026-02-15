import type { ResultData } from "../App";

interface ResultViewerProps {
  result: ResultData;
  apiUrl: string;
}

export default function ResultViewer({ result, apiUrl }: ResultViewerProps) {
  const plyPath = encodeURIComponent(result.gaussiansPly);
  const fileUrl = `${apiUrl}/runs/${result.runId}/file?path=${plyPath}`;
  const viewerUrl = `${apiUrl}/runs/${result.runId}/view`;
  const antimatterUrl = `https://antimatter15.com/splat/?url=${encodeURIComponent(fileUrl)}`;

  return (
    <div className="result active">
      <iframe
        className="viewer-frame"
        src={viewerUrl}
        frameBorder="0"
        title="3D Viewer"
      />
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
