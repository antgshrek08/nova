---
name: git-github
description: Git and GitHub workflow help -- commits, branches, merge conflicts, rebasing, PRs
keywords: [git, github, commit, branch, merge conflict, pull request, rebase, git stash, cherry-pick, force push, detached head]
---

When helping with git or GitHub:

1. Ask what the user is actually trying to accomplish before suggesting a command -- "how do I undo this" has very different right answers depending on whether the change is committed, pushed, or shared with anyone else.
2. Default to the least destructive option that solves the problem. Explicitly flag anything that rewrites history (rebase, force push, reset --hard, filter-branch) or is otherwise hard to undo, and confirm the user actually wants that before walking through it -- especially if a branch might already be pushed or shared.
3. For a merge conflict: explain what the conflict markers (<<<<<<<, =======, >>>>>>>) actually represent in this specific case before telling the user what to keep, rather than just picking a side for them.
4. Show the actual command(s) to run, not just a description of what to do -- this is a case where the literal syntax matters and paraphrasing it invites mistakes.
5. If the user seems to be fighting git out of confusion about what state they're in, run/suggest `git status` and `git log --oneline --graph` (or ask them to share the output) before prescribing a fix -- diagnose the actual state rather than guessing from the description alone.
6. For "how do I write a good commit message," push toward imperative mood, one logical change per commit, and a short body explaining *why* when the reason isn't obvious from the diff.
