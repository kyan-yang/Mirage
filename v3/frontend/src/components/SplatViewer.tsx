import { useEffect, useRef, useState } from "react";

interface SplatViewerProps {
  fileData: Uint8Array | null;
  fileName: string | null;
}

/**
 * In-browser Gaussian Splat viewer powered by Spark + Three.js.
 * Receives raw PLY/splat bytes and renders them on a canvas
 * with orbit / zoom / WASD controls.
 */
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

        const camera = new THREE.PerspectiveCamera(75, w / h, 0.01, 1000);
        camera.position.set(0, 0, 1);

        const scene = new THREE.Scene();

        const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
        renderer.setSize(w, h, false);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

        const controls = new SparkControls({ canvas });

        const resize = () => {
          const cw = container.clientWidth;
          const ch = container.clientHeight;
          if (cw === 0 || ch === 0) return;
          if (canvas.width !== cw || canvas.height !== ch) {
            renderer.setSize(cw, ch, false);
            camera.aspect = cw / ch;
            camera.updateProjectionMatrix();
          }
        };
        window.addEventListener("resize", resize);

        renderer.setAnimationLoop(() => {
          resize();
          controls.update(camera);
          renderer.render(scene, camera);
        });

        stateRef.current = {
          scene,
          camera,
          renderer,
          controls,
          splatMesh: null,
        };
        return true;
      } catch (e) {
        console.error("[SplatViewer] init error:", e);
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

      const bytes = fileData.slice(0);
      const initObj: any = { fileBytes: bytes };
      if (fileName) initObj.fileName = fileName;

      const splatMesh = new SplatMesh(initObj);
      splatMesh.quaternion.set(1, 0, 0, 0);
      scene.add(splatMesh);
      stateRef.current.splatMesh = splatMesh;

      camera.position.set(0, 0, 1);

      try {
        await splatMesh.initialized;
        if (cancelled) return;
        setSplatCount(splatMesh.numSplats ?? null);
      } catch (e) {
        console.warn("[SplatViewer] init await error:", e);
      }

      setIsLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [fileData, fileName]);

  return (
    <div className="splat-viewer-wrapper">
      <div ref={containerRef} className="splat-viewer-canvas" />

      {isLoading && (
        <div className="splat-viewer-loading">
          <span className="spinner" />
          <span>Loading splat...</span>
        </div>
      )}

      {!isLoading && fileData && fileName && (
        <div className="splat-viewer-hud">
          <span className="splat-viewer-dot" />
          <span>{fileName}</span>
          {splatCount !== null && (
            <>
              <span className="splat-viewer-sep">|</span>
              <span>{splatCount.toLocaleString()} splats</span>
            </>
          )}
        </div>
      )}

      {!isLoading && fileData && (
        <div className="splat-viewer-controls-hint">
          Click + drag to look &middot; WASD to move &middot; Scroll to zoom
        </div>
      )}
    </div>
  );
}
