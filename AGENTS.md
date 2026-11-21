# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

## Where things live

- GitHub issues: work items, with handoff notes in their comments; one milestone per step of the [app rebuild](doc/app-rebuild-plan.md).
- `doc/`: long-term knowledge: architecture and decisions ([index](doc/README.md)).
- `experiments/<date>-<topic>/`: one self-contained, pinned snapshot per experiment run (code, `pyproject.toml`/`uv.lock`, model and input hashes, aggregate results). Private data stays in ignored `tmp/`.

## Branches and pull requests

- Name branches `<type>/<summary>` with Conventional Commit types (`feat/publish-stage`, `fix/input-bindings`).
- Group PRs by theme. A fix for a bug already on `main` goes in its own small PR from `main`. A fix to work that hasn't merged yet is folded into the commit it fixes.
- The owner reviews branches locally before anything is pushed. Every PR's title and body are shown in chat for approval before it opens, as the `open-pr` skill requires.
- PRs are squash-merged. After a PR in a stack merges, rebase the next branch onto the new `main` (`git rebase --onto origin/main <old base commit> <branch>`) before filing it.
- Check the PR's state immediately before each push. If it merged, follow the `commit` skill's branch-safety rules instead of pushing to it.
- Use the `commit` skill for every commit.
