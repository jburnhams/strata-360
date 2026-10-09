## 13. Definition of done (v1)

- Point the tool at a race folder plus a GPX, and receive: `edl.json`, a review report, a draft preview, and the final flat 16:9 video with its `timemap.csv`. No manual export from vendor software in the normal path.
- Every output segment carries the right UTC start (verified by reading the MP4 tags back) and no timing change breaks the map overlay.
- All test cases above are automated (except those marked as needing real footage or the live LLM suite, which run on demand).
- A re-run with no changes does no expensive work.
- Any decision can be overridden by a file edit and reflected in the next run.

---
