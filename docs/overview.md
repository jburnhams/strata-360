# strata-360 overview: automated 360° race video editing pipeline

Turn dozens of short 360° clips shot during an ultramarathon (DJI 360 today, Insta360 for older races) into a single edited highlight film. The film is reframed to flat video, trimmed, optionally beat-synced to music, and stays time-aligned with the race GPX so an existing moving-map renderer can overlay it.

This document is the developer brief: goals, architecture, data contracts, phase-by-phase requirements, and a test plan for each phase. Code and other docs cite its sections as "README N" (it was the README until 1 Oct 2026). [`progress.md`](progress.md) is the running log of what was tried and learned; [`implementation-plan.md`](implementation-plan.md) is what to build next.

## Contents (one file per section; code cites them as "README N")

- [0. Quick start: running the pipeline on a new race collection](overview/00-quick-start-running-the-pipeline-on-a-ne.md)
- [1. Goals and non-goals](overview/01-goals-and-non-goals.md)
- [2. What we know about the input files](overview/02-what-we-know-about-the-input-files.md)
- [3. Architecture overview](overview/03-architecture-overview.md)
- [4. Repository layout](overview/04-repository-layout.md)
- [5. Data contracts](overview/05-data-contracts.md)
- [6. Time model and timestamp preservation](overview/06-time-model-and-timestamp-preservation.md)
- [7. Phase specifications](overview/07-phase-specifications.md)
- [8. Cross-cutting concerns](overview/08-cross-cutting-concerns.md)
- [9. Handoff contract to the existing map renderer (summary)](overview/09-handoff-contract-to-the-existing-map-ren.md)
- [10. Milestones (suggested order)](overview/10-milestones-suggested-order.md)
- [11. Risks and mitigations](overview/11-risks-and-mitigations.md)
- [12. Open questions and decisions](overview/12-open-questions-and-decisions.md)
- [13. Definition of done (v1)](overview/13-definition-of-done-v1.md)
- [14. Future work (flagged, not yet built)](overview/14-future-work-flagged-not-yet-built.md)
- [15. Analysis data: what we collect so edit points and framing can be decided later](overview/15-analysis-data-what-we-collect-so-edit-po.md)
- [16. Edit techniques, variety and the joint optimisation](overview/16-edit-techniques-variety-and-the-joint-op.md)
- [17. The voice-over-driven workflow](overview/17-the-voice-over-driven-workflow.md)
- [18. Workflow shape: batch everything, propose everything, edit in a fast GUI](overview/18-workflow-shape-batch-everything-propose.md)
