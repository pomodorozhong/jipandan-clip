# Web GUI migration archive

The browser GUI migration completed with owner approval on 2026-09-25. These documents preserve the design decisions and review history. Use the [project README](../../../README.md) for current installation and launch instructions; references here to running servers and disposable sessions are historical.

- [Porting plan](web-gui-porting-plan.md)
- [Owner review guide](your-web-gui-review-guide.md)
- [Checkpoint 2: review screen](web-review-checkpoint-2.md)
- [Checkpoint 2: control refinements](web-review-ui-refinements.md)
- [Checkpoint 3: waveform editing](web-review-checkpoint-3.md)
- [Checkpoint 4: rendered previews](web-review-checkpoint-4.md)
- [Checkpoint 5: complete session](web-review-checkpoint-5.md)
- Export preview concept: [HTML](mockups/export-preview-concept.html) and [image](mockups/export-preview-concept.png)

The fixture preparation helper remains at `scripts/prepare_web_review.py`, run from the repository root. It requires the private `raw/0526.*` recordings and session files; those fixtures are not included in Git.
