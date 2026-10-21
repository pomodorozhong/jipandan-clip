# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

<!-- handoff:start (from the handoff skill; edit the skill's template, not this copy) -->
## Handoff

`HANDOFF.md` at the repository root is how sessions resume. It has three sections: `In progress` (one `### <branch>` subsection per active branch, holding its state and its own approval requests), `Ranked work`, and `Pending` (approval requests not tied to a branch). A pending entry, such as `P-01`, records a request, not approval.

- **Start of a session:** read `HANDOFF.md` and the subsection named after `git branch --show-current`; no subsection means nothing is in progress on this branch. Compare its code checkpoint with `git log`, re-check verification that later commits may have made stale, and run the project's documented checks before building on it. If this branch's PR has merged or closed, apply the `commit` skill's branch-safety rules before new commits or pushes. Before recommending or starting work, show the user everything waiting on them and ask about it first: pending requests in this branch's subsection and under `Pending` (saying which ones a merge or close made obsolete), and the decisions `Ranked work` puts first. To pick new work, start from the default branch's `Ranked work`.
- **Edit only this branch's subsection,** plus `Ranked work` and `Pending` when they actually change. Keep it current rather than a log, and never write secrets.
- **Commit `HANDOFF.md`** only before a push and at wrap-up, as a `docs:` commit on the work branch. Never commit it on the default branch.
- **PRs:** use the `open-pr` skill, and keep its unanswered approval requests in this branch's subsection until they are resolved. **End of a session:** use the `handoff` skill.
- **Before creating a branch, editing `HANDOFF.md`, or resolving a conflict in it,** read the `handoff` skill's working rules (`references/working-rules.md` in that skill).
<!-- handoff:end -->

## Where things live

- GitHub issues: work items, with handoff notes in their comments; one milestone per step of the [app rebuild](doc/app-rebuild-plan.md).
- `HANDOFF.md`: per-branch resume points, the ranked list of issues to work on next, and pending approvals.
- `doc/`: long-term knowledge: architecture and decisions ([index](doc/README.md)).

## Branches and pull requests

- Name branches `<type>/<summary>` with Conventional Commit types (`feat/publish-stage`, `fix/input-bindings`).
- Group PRs by theme. A fix for a bug already on `main` goes in its own small PR from `main`. A fix to work that hasn't merged yet is folded into the commit it fixes.
- The owner reviews branches locally before anything is pushed. Every PR's title and body are shown in chat for approval before it opens, as the `open-pr` skill requires.
- PRs are squash-merged. After a PR in a stack merges, rebase the next branch onto the new `main` (`git rebase --onto origin/main <old base commit> <branch>`) before filing it.
- Before every push, update `Ranked work` in `HANDOFF.md` to read as it will after that branch merges, in the `docs:` commit the handoff rules require before a push.
- Check the PR's state immediately before each push. If it merged before the branch's last `docs:` commit was pushed, carry that commit's changes into the next work branch's `docs:` commit; never open a PR that changes only `HANDOFF.md`.
- Use the `commit` skill for every commit.
