⏺ User approved Claude's plan
  ⎿  Plan saved to: ~/.claude/plans/inherited-munching-minsky.md
      · /plan to edit

     Scenario Generator — Text Prompt → Video → 3D World

     Context

     Build a new app (separate folder v3/) for generating 3D
     training data for unique scenarios.
     User types a prompt like "road with fallen tree" → Gemini
     expands it → Google Veo generates a video →
     HunyuanWorld-Mirror converts video to 3D gaussian splat →
     Spark.js viewer displays it.

     Architecture

     [Frontend HTML]  →  [Modal: expand_prompt (Gemini)]
                      →  [Modal: generate_video (Veo 3.1)]
                      →  [Modal: generate_world
     (HunyuanWorld-Mirror)]
                      →  [Spark.js Viewer]

     Files to Create

     v3/modal_app.py — Single Modal app with 4 functions:

     1. expand_prompt(text: str) -> str (no GPU needed)
       - Calls Gemini (via google-genai SDK) to expand a short
     scenario description into a detailed cinematic video prompt
       - System prompt: "You are a cinematographer. Turn this
     scenario into a detailed 8-second video description with
     camera movement, lighting, and environment details suitable
      for 3D reconstruction. Keep the camera moving slowly
     forward through the scene."
       - Uses GEMINI_API_KEY secret
     2. generate_video(prompt: str, run_id: str) -> bytes (no
     GPU needed, just API call + polling)
       - Calls client.models.generate_videos(model="veo-3.1-gene
     rate-preview", prompt=...,
     config=types.GenerateVideosConfig(aspect_ratio="16:9",
     resolution="720p"))
       - Polls operation.done every 10s
       - Saves video to volume, returns video bytes
       - Uses GEMINI_API_KEY secret
     3. generate_world(video_bytes, run_id, ...) -> dict (H100
     GPU)
       - Reuse pattern from v2: write video to run_dir, run
     infer.py, find gaussians.ply
       - Same image/volume setup as v2
       - Returns {run_id, files, gaussians_ply}
     4. viewer() → FastAPI (no GPU)
       - GET / — frontend HTML page with prompt input
       - POST /generate — kicks off the full pipeline (expand →
     video → 3D), returns run_id + SSE progress
       - GET /runs/{run_id} — JSON file list
       - GET /runs/{run_id}/file?path=... — serve files
       - GET /runs/{run_id}/view — Spark.js viewer page for the
     splat

     v3/frontend.html (embedded as string in modal_app.py)

     - Clean dark UI with:
       - Text input for scenario prompt
       - "Generate" button
       - Progress steps display (expanding prompt → generating
     video → building 3D world)
       - When done: embedded Spark.js viewer showing the splat

     Spark.js Viewer (embedded in the viewer endpoint HTML)

     - Uses CDN import map for Three.js + @sparkjsdev/spark
     - Loads .ply directly via new SplatMesh({ url:
     "/runs/{run_id}/file?path=gaussians.ply" })
     - Orbit controls for navigation
     - Supports .ply natively (auto-detected)

     Modal Setup

     - App name: "scenario-gen"
     - Volumes: reuse world-mirror-v2-weights for cached model
     weights, new scenario-gen-artifacts for runs
     - Image: same CUDA/PyTorch image as v2 + google-genai pip
     package
     - Secrets: modal.Secret.from_name("gemini-api-key") with
     GEMINI_API_KEY

     CLI Entrypoint (main())

     modal run v3/modal_app.py --prompt "road with fallen tree
     blocking traffic"
     - Calls expand_prompt → generate_video → generate_world
     sequentially
     - Prints viewer URL at end
     - Also opens browse page (reuse from v2)

     Key Reuse from v2

     - generate_world() logic (write inputs, run infer.py, find
     ply, build preview) — adapted for video-only input
     - Helper functions: _run(), _safe_mkdir(), _list_files(),
     _hf_env(), _build_web_preview()
     - Modal image definition (CUDA + PyTorch +
     HunyuanWorld-Mirror)
     - Volume for weights cache

     API Keys Needed

     - GEMINI_API_KEY — for both Gemini prompt expansion and Veo
      video generation (same key)
     - Set as Modal secret: modal secret create gemini-api-key
     GEMINI_API_KEY=<key>

     Verification

     1. modal secret create gemini-api-key GEMINI_API_KEY=<key>
     2. modal run v3/modal_app.py --prompt "road with fallen
     tree"
     3. Check: prompt expansion prints expanded prompt
     4. Check: video generation completes and saves .mp4
     5. Check: HunyuanWorld-Mirror produces gaussians.ply
     6. Check: viewer URL opens with Spark.js showing the splat
     7. modal deploy v3/modal_app.py for persistent frontend