# AGENTS.md

This repo builds a web app where a user uploads images → we generate a 3D Gaussian Splat scene → we segment the splats into objects → (stretch) we let the user move objects around.

## Product flow (high-level)
1. User uploads one or more images.
2. Backend creates a splat scene:
   - Preferred: World Labs API (if credentials available).
   - Fallback: open-source splat training pipeline (images + poses → trained splats).
3. Backend runs segmentation (Plan A):
   - Render many views of the splat scene.
   - Run 2D segmentation on each rendered view.
   - Render an “ID buffer” (pixel → splat id) for each view.
   - Vote labels onto splats; cluster splats into instances.
4. Frontend viewer:
   - Loads splats + segmentation metadata.
   - Supports highlight/hide/select by instance.
   - Stretch: drag/move object proxies (see “Object moving” below).

## Repo layout (expected; adjust if different)
- `web/` — frontend viewer + upload UI
- `server/` — API server (upload, queue jobs, serve results)
- `pipelines/` — world generation + segmentation jobs
- `data/` — local dev artifacts (ignored by git)
- `scripts/` — one-off utilities (download, convert formats)

If the repo differs, update this file to match the actual structure.

## Key artifacts & formats
- Splats: `.spz` / `.splat` / `.ply` (depends on generator + renderer)
- Segmentation outputs:
  - `instances.json`: list of instance IDs with label/name + bounding boxes + splat indices
  - `splat_labels.bin` (optional): per-splat instance id array for fast lookup
  - `thumbnails/`: per-instance preview renders (optional)

## Render + segmentation “Plan A” (implementation guidance)
Goal: establish pixel↔splat correspondence to vote 2D labels onto 3D splats.

Required renderer feature:
- An additional render pass that outputs an **ID buffer**:
  - For each pixel, store the splat id that contributed most to that pixel.
  - Prefer 32-bit integer render target (or RGBA-packed id).

Algorithm sketch:
1. Sample N camera poses around the scene (N ~ 30–150).
2. For each pose:
   - Render RGB image.
   - Render splat-ID buffer (same resolution).
   - Run 2D segmentation on RGB (semantic and/or instance masks).
   - For each pixel in mask:
     - `sid = id_buffer[p]`
     - `votes[sid, class_or_instance] += weight` (weight optional; can use confidence)
3. For each splat:
   - assign label = argmax votes
4. Cluster splats (same label) in 3D to get instances.

When implementing: prefer deterministic + debuggable outputs
- Save a few frames: `rgb.png`, `id.png`, `mask.png` overlays.
- Write a small “sanity report” (counts, top labels, orphan splats).

## Object moving (stretch)
Moving splats directly is not reliable for “object editing” because splats are not a rigid object graph.
Stretch implementation should use:
- A selected instance → hide its splats (or render with zero alpha)
- Spawn a separate movable asset (GLB) as a proxy object
- Keep proxy aligned with the original instance bbox/pose

If implementing true rigid transforms on splat subsets:
- Keep it as a demo feature only (expect artifacts).
- Apply transform to splat centers + orientations for the chosen instance ID.

## External services & secrets
- World Labs API key(s): store in `.env` (never commit).
- If using Modal: store Modal token/secret in `.env` or Modal secrets.

Add a `.env.example` with all required variables.

## Development commands
Once the stack is chosen, update this section to match reality.

## Conventions for agents working in this repo
- Keep changes small and testable; do one task per thread.
- Before editing, locate the relevant entry points:
  - upload endpoint
  - job queue / pipeline runner
  - viewer load path for splats + segmentation metadata
- Prefer adding debug outputs that are easy to inspect:
  - write rendered frames and overlays to `data/debug/<run_id>/`
- Don’t “silently” change formats:
  - if you change output JSON schema or binary layouts, update both producer and consumer and document in this file.

## TODO to fill in (project-specific)
- [ ] Choose renderer (SparkJS vs other) and document how to enable ID buffer.
- [ ] Choose 2D segmentation model and document how to run it locally.
- [ ] Decide where jobs run (local vs Modal) and document the entry command(s).
- [ ] Document exact output formats and paths used by the viewer.
