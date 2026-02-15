"use client";

import { useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";

const SplatViewer = dynamic(() => import("./components/SplatViewer"), {
  ssr: false,
});

export default function Home() {
  const [fileData, setFileData] = useState<Uint8Array | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCountRef = useRef(0);

  const handleFile = useCallback((file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    const validExtensions = ["ply", "splat", "spz", "ksplat"];

    if (!ext || !validExtensions.includes(ext)) {
      setError(
        `Unsupported format: .${ext}. Use .ply, .splat, .spz, or .ksplat`
      );
      setTimeout(() => setError(null), 4000);
      return;
    }

    setError(null);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = (e) => {
      const buf = e.target?.result;
      if (buf instanceof ArrayBuffer) {
        // Store as Uint8Array – safe, owned copy
        setFileData(new Uint8Array(buf));
      }
    };
    reader.onerror = () => {
      setError("Failed to read file");
      setTimeout(() => setError(null), 4000);
    };
    reader.readAsArrayBuffer(file);
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCountRef.current++;
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCountRef.current--;
    if (dragCountRef.current === 0) setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCountRef.current = 0;
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
      // reset so the same file can be re-selected
      e.target.value = "";
    },
    [handleFile]
  );

  const hasFile = fileData !== null;

  return (
    <div
      className="relative flex h-screen w-screen flex-col overflow-hidden"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Background gradient */}
      <div className="pointer-events-none absolute inset-0 z-0">
        <div className="absolute left-1/2 top-0 h-[600px] w-[800px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--accent)] opacity-[0.03] blur-[120px]" />
        <div className="absolute bottom-0 right-0 h-[400px] w-[600px] translate-x-1/4 translate-y-1/4 rounded-full bg-[var(--accent)] opacity-[0.02] blur-[100px]" />
      </div>

      {/* Top bar */}
      <header className="relative z-20 flex h-14 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--background)] px-5">
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--accent-dim)]">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                stroke="var(--accent)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <span className="text-sm font-medium tracking-tight text-[var(--foreground)]">
            Splat Viewer
          </span>
          <span className="rounded-full bg-[var(--accent-dim)] px-2 py-0.5 font-mono text-[10px] font-medium text-[var(--accent)]">
            SPARK
          </span>
        </div>

        <div className="flex items-center gap-2">
          {hasFile && (
            <button
              onClick={() => {
                setFileData(null);
                setFileName(null);
              }}
              className="rounded-md border border-[var(--border)] px-3 py-1.5 font-mono text-xs text-[var(--muted)] transition-all hover:border-[var(--border-hover)] hover:text-[var(--foreground)]"
            >
              Clear
            </button>
          )}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1.5 font-mono text-xs text-[var(--foreground)] transition-all hover:border-[var(--border-hover)] hover:bg-white/[0.04]"
          >
            Open file
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".ply,.splat,.spz,.ksplat"
            onChange={handleFileInput}
            className="hidden"
          />
        </div>
      </header>

      {/* Main area — viewer is ALWAYS mounted, drop zone overlays it */}
      <main className="relative z-10 flex-1 overflow-hidden">
        {/* 3D viewer — always alive in background */}
        <div className="absolute inset-0">
          <SplatViewer fileData={fileData} fileName={fileName} />
        </div>

        {/* Drop zone — shown over the viewer when no file loaded */}
        {!hasFile && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--background)] p-8">
            <div
              className={`group relative flex h-full max-h-[600px] w-full max-w-[800px] cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-all duration-300 ${
                isDragging
                  ? "border-[var(--accent)] bg-[var(--accent-dim)] shadow-[0_0_80px_-20px_var(--accent)]"
                  : "border-[var(--border)] hover:border-[var(--border-hover)] hover:bg-white/[0.01]"
              }`}
              onClick={() => fileInputRef.current?.click()}
            >
              {/* Corners */}
              {["left-4 top-4 border-l-2 border-t-2", "right-4 top-4 border-r-2 border-t-2", "bottom-4 left-4 border-b-2 border-l-2", "bottom-4 right-4 border-b-2 border-r-2"].map((pos) => (
                <div
                  key={pos}
                  className={`absolute h-4 w-4 ${pos} transition-colors duration-300 ${
                    isDragging ? "border-[var(--accent)]" : "border-white/10"
                  }`}
                />
              ))}

              {/* Icon */}
              <div
                className={`mb-6 flex h-16 w-16 items-center justify-center rounded-2xl transition-all duration-300 ${
                  isDragging
                    ? "scale-110 bg-[var(--accent)]/20"
                    : "bg-white/[0.03] group-hover:bg-white/[0.05]"
                }`}
              >
                <svg
                  width="28"
                  height="28"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className={`transition-all duration-300 ${
                    isDragging ? "text-[var(--accent)]" : "text-[var(--muted)]"
                  }`}
                >
                  <path
                    d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>

              <h2
                className={`mb-2 text-lg font-medium tracking-tight transition-colors ${
                  isDragging
                    ? "text-[var(--accent)]"
                    : "text-[var(--foreground)]"
                }`}
              >
                {isDragging ? "Drop to visualize" : "Drop a splat file here"}
              </h2>
              <p className="mb-4 max-w-sm text-center text-sm leading-relaxed text-[var(--muted)]">
                Drag and drop a Gaussian Splat file to render it in 3D.
                Supports orbit, zoom, and pan controls.
              </p>

              <div className="flex items-center gap-2">
                {[".ply", ".splat", ".spz", ".ksplat"].map((ext) => (
                  <span
                    key={ext}
                    className="rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-0.5 font-mono text-[11px] text-[var(--muted)]"
                  >
                    {ext}
                  </span>
                ))}
              </div>

              <p className="mt-6 text-xs text-[var(--muted)]/50">
                or click to browse
              </p>
            </div>
          </div>
        )}

        {/* Drag overlay when viewer is active */}
        {hasFile && isDragging && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#050505]/90 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed border-[var(--accent)] bg-[var(--accent-dim)] px-16 py-12">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                className="text-[var(--accent)]"
              >
                <path
                  d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <p className="text-lg font-medium text-[var(--accent)]">
                Drop to replace
              </p>
            </div>
          </div>
        )}
      </main>

      {/* Error toast */}
      {error && (
        <div className="absolute bottom-6 left-1/2 z-50 -translate-x-1/2 animate-fade-in">
          <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 backdrop-blur-md">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              className="shrink-0 text-red-400"
            >
              <circle
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="2"
              />
              <path
                d="M15 9l-6 6M9 9l6 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
            <span className="text-sm text-red-300">{error}</span>
          </div>
        </div>
      )}
    </div>
  );
}
