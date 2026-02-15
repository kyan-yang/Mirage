"use client";

/**
 * Matches the official Spark viewer pattern from:
 * https://github.com/sparkjsdev/spark/blob/main/examples/viewer/index.html
 *
 * Key differences from our previous attempts:
 * 1. No explicit SparkRenderer — Spark auto-creates one internally.
 * 2. Pass `fileName` to SplatMesh so it can detect .splat/.ksplat formats.
 * 3. No position override on the splat — let it load at origin.
 * 4. SparkControls handles ALL navigation (mouse + WASD/arrows) — no custom handler.
 * 5. Camera starts at (0, 0, 1) with FOV 75 (matches official viewer).
 */

import { useEffect, useRef, useState } from "react";

interface SplatViewerProps {
  fileData: Uint8Array | null;
  fileName: string | null;
}

export default function SplatViewer({ fileData, fileName }: SplatViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<{
    scene: any;
    camera: any;
    renderer: any;
    controls: any;
    splatMesh: any;
  } | null>(null);
  const initPromise = useRef<Promise<boolean> | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [splatCount, setSplatCount] = useState<number | null>(null);

  // ── one-time scene bootstrap ──
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let dead = false;

    initPromise.current = (async () => {
      try {
        const THREE = await import("three");
        const { SparkControls } = await import("@sparkjsdev/spark");
        if (dead) return false;

        const canvas = document.createElement("canvas");
        canvas.style.display = "block";
        canvas.style.width = "100%";
        canvas.style.height = "100%";
        container.appendChild(canvas);

        const w = container.clientWidth;
        const h = container.clientHeight;

        // Camera — same as official Spark viewer
        const camera = new THREE.PerspectiveCamera(75, w / h, 0.01, 1000);
        camera.position.set(0, 0, 1);

        const scene = new THREE.Scene();

        // Renderer — use the canvas we created
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
        renderer.setSize(w, h, false);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        // SparkControls — handles mouse orbit, scroll zoom, WASD, arrow keys
        const controls = new SparkControls({ canvas });

        // Resize handler
        const resize = () => {
          const cw = container.clientWidth;
          const ch = container.clientHeight;
          if (cw === 0 || ch === 0) return;
          const needResize = canvas.width !== cw || canvas.height !== ch;
          if (needResize) {
            renderer.setSize(cw, ch, false);
            camera.aspect = cw / ch;
            camera.updateProjectionMatrix();
          }
        };
        window.addEventListener("resize", resize);

        // Animation loop — exactly matches official viewer
        renderer.setAnimationLoop(() => {
          resize();
          controls.update(camera);
          renderer.render(scene, camera);
        });

        stateRef.current = { scene, camera, renderer, controls, splatMesh: null };
        console.log("[Spark] init complete ✓  canvas:", w, "×", h);
        return true;
      } catch (e: any) {
        console.error("[Spark] init error:", e);
        return false;
      }
    })();

    return () => {
      dead = true;
      if (stateRef.current) {
        stateRef.current.renderer?.setAnimationLoop(null);
        stateRef.current.renderer?.dispose();
        stateRef.current.renderer?.domElement?.remove();
        stateRef.current = null;
      }
    };
  }, []);

  // ── load / swap splat when fileData changes ──
  useEffect(() => {
    if (!fileData) {
      if (stateRef.current?.splatMesh && stateRef.current?.scene) {
        stateRef.current.scene.remove(stateRef.current.splatMesh);
        stateRef.current.splatMesh.dispose?.();
        stateRef.current.splatMesh = null;
      }
      setSplatCount(null);
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    (async () => {
      const ok = await initPromise.current;
      if (cancelled || !ok || !stateRef.current) return;

      const { scene, camera } = stateRef.current;

      setIsLoading(true);

      const { SplatMesh } = await import("@sparkjsdev/spark");
      if (cancelled) return;

      // Remove previous splat
      if (stateRef.current.splatMesh) {
        scene.remove(stateRef.current.splatMesh);
        stateRef.current.splatMesh.dispose?.();
        stateRef.current.splatMesh = null;
      }

      // Exactly matches official Spark viewer:
      //   fileBytes = new Uint8Array(await splatFile.arrayBuffer());
      //   fileName = splatFile.name;
      //   setSplatFile({ fileBytes: fileBytes.slice(), fileName });
      //
      //   loadedSplat = new SplatMesh(init);
      //   loadedSplat.quaternion.set(1, 0, 0, 0);
      //   scene.add(loadedSplat);

      const bytes = fileData.slice(0);
      console.log("[Spark] loading splat:", fileName, "bytes:", bytes.byteLength);

      const initObj: any = { fileBytes: bytes };
      if (fileName) initObj.fileName = fileName;

      const splatMesh = new SplatMesh(initObj);
      splatMesh.quaternion.set(1, 0, 0, 0);
      scene.add(splatMesh);
      stateRef.current.splatMesh = splatMesh;

      // Reset camera for the new file
      camera.position.set(0, 0, 1);

      // Wait for initialization to get splat count
      try {
        await splatMesh.initialized;
        if (cancelled) return;
        console.log("[Spark] loaded ✓ splats:", splatMesh.numSplats);
        setSplatCount(splatMesh.numSplats ?? null);
      } catch (e) {
        console.warn("[Spark] init await error:", e);
      }

      setIsLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [fileData, fileName]);

  const showHUD = fileData !== null && !isLoading;

  return (
    <div className="relative h-full w-full">
      {/* Canvas container */}
      <div ref={containerRef} className="h-full w-full bg-[#2b2928]" />

      {/* Loading spinner */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#050505]/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-4">
            <div className="relative h-10 w-10">
              <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-[var(--accent)]" />
              <div
                className="absolute inset-1 animate-spin rounded-full border-2 border-transparent border-b-[var(--accent)]"
                style={{ animationDirection: "reverse", animationDuration: "1.5s" }}
              />
            </div>
            <p className="text-sm font-medium text-[var(--foreground)]">Loading splat...</p>
          </div>
        </div>
      )}

      {/* File info badge */}
      {showHUD && fileName && (
        <div className="absolute left-4 top-4 animate-fade-in">
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]/80 px-3 py-1.5 backdrop-blur-md">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="font-mono text-xs text-[var(--muted)]">{fileName}</span>
            {splatCount !== null && (
              <>
                <span className="text-white/10">|</span>
                <span className="font-mono text-xs text-[var(--muted)]">
                  {splatCount.toLocaleString()} splats
                </span>
              </>
            )}
          </div>
        </div>
      )}

      {/* Controls hint */}
      {showHUD && (
        <div className="absolute bottom-4 right-4 animate-fade-in">
          <div className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]/60 px-3 py-1.5 backdrop-blur-md">
            <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--muted)]">
              Click + drag to look &middot; WASD / Arrows to move &middot; Scroll to zoom
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
