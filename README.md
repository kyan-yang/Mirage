# HunyuanWorld on Modal

## Model choice for agents/segmentation

If you need a persistent 3D world representation (mesh/assets you can inspect, segment, and attach agents to), start with **HunyuanWorld-1.0**.

Use **HunyuanWorld-1.5 (WorldPlay)** when you primarily want interactive world-model video generation. It is stronger for real-time playable dynamics, but its default outputs are not as directly agent-friendly as an explicit 3D scene asset pipeline.

## Files in this repo

- `/Users/shreybirmiwal/treehacks-2026/modal_hunyuanworld.py`: Modal app for generating worlds with HunyuanWorld-1.0 and serving artifacts.

## Prereqs

1. Install Modal locally:

```bash
pip install modal
python3 -m modal setup
```

2. Create a Modal secret named `huggingface-token`:

```bash
modal secret create huggingface-token HUGGINGFACE_TOKEN=hf_xxx
```

## Run a generation job

Text-to-world:

```bash
modal run /Users/shreybirmiwal/treehacks-2026/modal_hunyuanworld.py::main --prompt "an alpine valley at sunrise" --classes outdoor
```

Image-to-world:

```bash
modal run /Users/shreybirmiwal/treehacks-2026/modal_hunyuanworld.py::main --image-path /absolute/path/to/input.png --classes outdoor --labels-fg1 rocks,trees --labels-fg2 mountains,clouds
```

## Deploy artifact viewer

```bash
modal deploy /Users/shreybirmiwal/treehacks-2026/modal_hunyuanworld.py
```

The app exposes:

- `GET /` list run IDs
- `GET /runs/{run_id}` list files for a run
- `GET /runs/{run_id}/file?path=modelviewer.html` open viewer
- `GET /runs/{run_id}/file?path=<artifact-path>` download any artifact

## Notes

- This setup uses `A100-80GB` for headroom. You can downgrade later if memory allows.
- First build can take a while due to model dependencies.
- If you need a world-state API for autonomous agents, the next step is adding a post-process stage that normalizes generated artifacts into a scene graph (entities, transforms, semantic tags).
