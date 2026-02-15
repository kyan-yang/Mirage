## Notes
Dont view the contents of `archive/`. That code is old and outdated versions.

## Code Organization Principles
- Prefer fewer, semantically distinct top-level folders (target ~5–12)
- Enforce consistent conventions (same type of code always in the same place)
- Minimize duplication and ambiguity (one utils/, one api/ per domain)
- Keep each unit self-contained
- **IMPORTANT**: Prefer logical, clean, modular, robust designs. Avoid overengineered flows.

## Abstraction Judgment
- **Measure abstraction by what it costs to not have it, not by line count.** A 3-line wrapper that two apps import is justified if the alternative is duplicated `useEffect` + `useState` blocks in both. "Remove it for simplicity" is wrong if removing it moves complexity into every consumer.
- **An abstraction is premature when it encodes an assumption you haven't validated.** A hook that dictates data access patterns before the UI exists is risky — not because it's code, but because it might be the wrong API. Thin wrappers over storage reads are low-risk; opinionated data-shaping hooks are higher-risk.
- **The trigger for adding abstraction is multiple consumers with diverging needs, not future speculation.** Two apps (popup, panel) reading different slices of the same storage already justifies per-slice access. "We might need this later" does not.
- **Never delete an abstraction only to reintroduce it one phase later.** If the roadmap already contains the feature that requires the abstraction (e.g., live pricing creates independent refresh lifecycles), keep the abstraction. Churn is not simplicity.

## Workflow
- **IMPORTANT**: Use parallel subagents to do your work for you. Avoid polluting your own context
- **IMPORTANT**: NEVER GUESS API ENDPOINTS. Check docs and github repos first.

## Writing Style for Plans & Docs
- **No code blobs in plans.** Communicate ideas with word specificity, not code.
- Describe what each function/module receives, does, and returns in prose.
- Name concrete files, functions, and types for consistency, but do not write their implementations.
- Diagrams (architecture, file trees) are fine — they are visual aids, not code.

# folder structure:
- google maps data: has scripts to take a google maps location and extract 360 panoramic pictures from it with degrees / etc
- /modal: world-mirror.py generates a world model ply file but has messy code
- /v2: same thing as /modal but cleaner code and has a dashboard to see all results easier
- /v3: has a new pipeling: you type ina prompt, "tree falled on road", gemini creates a video, then it goes through world model to create a world model then displays it on a splat viewer