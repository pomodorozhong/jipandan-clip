# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

<!-- handoff:start (from the handoff skill; edit the skill's template, not this copy) -->
## Handoff

`HANDOFF.md` at the repository root is how sessions resume. It is committed on every branch, including the default branch, and has three sections: `In progress` (one `### <branch>` subsection per active branch, holding that branch's state and its own approval requests), `Ranked work`, and `Pending` (approval requests not tied to a branch, such as issue drafts). Approval requests have stable IDs (`P-01`), the proposed action and scope, why approval is needed, and what they block.

### Start of a session

- Read `HANDOFF.md` and find the subsection named after the current branch (`git branch --show-current`). No subsection means nothing is in progress on this branch.
- To pick new work, start from the default branch's `Ranked work`. To resume an issue from another computer, find its branch with `gh issue develop --list <N>`, fetch it, and read that branch's `HANDOFF.md`. Preserve local changes when switching checkouts.
- Compare the subsection's code checkpoint with `git log`; list commits made after it, skipping the branch's own `docs:` commits that only touch `HANDOFF.md` or the docs folder, and re-check verification the rest may have made stale. Run the project's documented checks before building on the previous session's work.
- Verify issue and PR status when GitHub is available. If the PR has merged or closed, apply the `commit` skill's branch-safety rules before new commits or pushes. A subsection whose PR has merged or closed is stale: remove it in your next `docs:` commit, moving anything unresolved to the issue or to `Pending`.
- A pending entry records a request, not approval. Handle only the approvals the chosen action needs, and continue other authorized work.

### During work

- Create each work branch from its primary issue: `gh issue develop <N> --name <type>/<summary> --base <default branch> --checkout` (or `--worktree <path>`). This creates the branch on GitHub at once, so it needs the same authorization as a push; without it, create the branch locally and link it when pushing is approved. If the work has no issue yet, create the branch locally, add an issue draft to its subsection's pending requests, and link the branch once the issue is filed. The PR may close other issues too; list each with `Closes #N`.
- Link a branch to an issue only when its PR will fully resolve that issue: when the PR merges, GitHub closes every issue linked to its branch, even if the body says `Related to #N`. A branch that only advances an issue, or only carries a handoff, is created locally and stays unlinked.
- Open PRs with the `handoff` skill's PR procedure: the user approves a detailed plan before any work, and approves the finished branch before anything is pushed.
- Edit only the current branch's subsection, plus `Ranked work` and `Pending` when they actually change. Keep subsections in alphabetical order. Remove subsections whose PR has merged or closed.
- The branch subsection records: task and issue, PR, code checkpoint, observed state, verification run and results, one concrete next action, and when useful: checks not run, approaches to avoid, and pending IDs with what they block. Describe unmerged work as awaiting review or merge.
- Keep it current rather than a log. History and decisions belong on the issue; lasting knowledge belongs in the docs folder. Never write secrets or local paths containing personal IDs.
- Commit `HANDOFF.md` only before a push and at wrap-up, as a `docs:` commit on the work branch. Never commit it on the default branch; with no work branch, commit it on the next task's branch, created as above.
- On a rebase conflict in `HANDOFF.md`, keep the incoming version of this branch's subsection and the base's version of everything else.

### End of a session

- Use the `handoff` skill to update issues and `HANDOFF.md`, resolve relevant pending requests, checkpoint intended changes, and report what is committed, uncommitted, and retrievable on another computer. Push only within the user's authorization.
<!-- handoff:end -->

## Where things live

- GitHub issues: work items, with handoff notes in their comments; one milestone per step of the [app rebuild](doc/app-rebuild-plan.md).
- `HANDOFF.md`: per-branch resume points, the ranked list of issues to work on next, and pending approvals.
- `doc/`: long-term knowledge: architecture and decisions ([index](doc/README.md)).

## Branches and pull requests

- Name branches `<type>/<summary>` with Conventional Commit types (`feat/publish-stage`, `fix/input-bindings`).
- Group PRs by theme. A fix for a bug already on `main` goes in its own small PR from `main`. A fix to work that hasn't merged yet is folded into the commit it fixes.
- The owner reviews branches locally before anything is pushed. Every PR's title and body are shown in chat for approval before it opens, as the handoff PR procedure requires.
- PRs are squash-merged. After a PR in a stack merges, rebase the next branch onto the new `main` (`git rebase --onto origin/main <old base commit> <branch>`) before filing it.
- Before every push, update `Ranked work` in `HANDOFF.md` to read as it will after that branch merges, in the `docs:` commit the handoff rules require before a push.
- Check the PR's state immediately before each push. If it merged before the branch's last `docs:` commit was pushed, move that commit to a new `docs/<summary>` branch from `main` and open a small docs PR instead.
- Use the `commit` skill for every commit.
