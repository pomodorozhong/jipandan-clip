# Documentation

See the [project README](../README.md) for installation, commands, and testing.

## Reference

- [Architecture](architecture.md): how the browser, server, SQLite store, FFmpeg, and Whisper fit together, and how input is handled.

## Active plans

- [App rebuild plan](app-rebuild-plan.md): the staged rebuild, its scope, and the decisions behind each step. Open work is in GitHub issues, one milestone per step.
- [Step 2 UI mockup](mockups/step-2-ui/README.md): the approved shared style for Triage, Polish, and the top bar.

## Completed work

The [web GUI migration archive](archive/web-gui-migration/README.md) preserves the completed plan, owner review checkpoints, design mockups, and the TUI user flow review that started the migration. Its launch URLs and disposable test sessions describe the builds reviewed at the time; they do not indicate running servers or available fixtures today.

The [browser input navigation archive](archive/input-navigation/README.md) preserves the completed IME and gamepad implementation plan and the IME event probe record.

Keep new project plans directly in `doc/` while work is active. Move completed plans and their supporting review material together into a named folder under `doc/archive/`, preserving their links.
