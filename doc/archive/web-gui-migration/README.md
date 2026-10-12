# Web GUI migration archive

The browser GUI migration completed with owner approval on 2026-09-25. These documents preserve the design decisions and review history. Use the [project README](../../../README.md) for current installation and launch instructions; references here to running servers and disposable sessions are historical.

- [Porting plan](web-gui-porting-plan.md)
- [TUI user flow review](tui-user-flow-issues.md): the findings the migration set out to fix first
- [Owner review guide](your-web-gui-review-guide.md)
- [Checkpoint 2: review screen](web-review-checkpoint-2.md)
- [Checkpoint 2: control refinements](web-review-ui-refinements.md)
- [Checkpoint 3: waveform editing](web-review-checkpoint-3.md)
- [Checkpoint 4: rendered previews](web-review-checkpoint-4.md)
- [Checkpoint 5: complete session](web-review-checkpoint-5.md)
- Export preview concept: [HTML](mockups/export-preview-concept.html) and [image](mockups/export-preview-concept.png)

The fixture preparation helper remains at `scripts/prepare_web_review.py`, run from the repository root. It now copies only the private `raw/0526.mp3` and `raw/0526.srt`, which are not included in Git; the GUI starts a fresh session database from the SRT. Checkpoints that mention copies of `raw/0526.jipandan.json` describe the JSON session format of the time, which current builds no longer open.
