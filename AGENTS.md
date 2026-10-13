# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

## Start of a session

1. Resolve any items parked in `.agents/pending.md` (see the `wrap-up` skill).
2. Read [.agents/next-steps.md](.agents/next-steps.md).
3. Check that the top issue is still open (`gh issue view`), then propose it to the owner.

## Where things live

- GitHub issues: work items, with handoff notes in their comments; one milestone per step of the [app rebuild](doc/app-rebuild-plan.md).
- `.agents/next-steps.md`: the ranked list of issues to work on next.
- `doc/`: long-term knowledge: architecture and decisions ([index](doc/README.md)).

## Branches and pull requests

- Name branches `<type>/<summary>` with Conventional Commit types (`feat/publish-stage`, `fix/input-bindings`).
- Group PRs by theme. A fix for a bug already on `main` goes in its own small PR from `main`. A fix to work that hasn't merged yet is folded into the commit it fixes.
- The owner reviews branches locally before anything is pushed, and may ask for the PR description to be drafted in chat first.
- PRs are squash-merged. After a PR in a stack merges, rebase the next branch onto the new `main` (`git rebase --onto origin/main <old base commit> <branch>`) before filing it.

## End of a session

Run the `wrap-up` skill to leave handoff notes on the issues, re-rank next steps, move lasting knowledge into `doc/`, and commit. Use the `commit` skill for any other commit.
