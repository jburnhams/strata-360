## Milestone D: editing in the GUI is fast

### D1. Timeline editing (M)
- Drag a window's edges; they snap to beats and to safe cut points with the V5 rules (never into dialogue).
- "Suggest again" for one window or a selected range (re-plan only the unlocked part with a new seed); keep the last three versions to step back.
- A map strip under the timeline (positions from `gps/context.py`).
- **Done when:** web integration tests (msw) for drag-snap and suggest-again; Python unit tests for the partial re-plan leaving locked windows identical (P5-30).

### D2. Live technique preview (L, optional)
- The WebGL player already projects the proxy; drive it from a window's camera path (`render/camera.py` maths in TypeScript), so changing a technique previews instantly without the HLS render.
- **Done when:** a unit test compares the TypeScript path evaluation with the Python one on the example paths in `spike/` (same yaw, pitch, fov to 0.01 degrees).
