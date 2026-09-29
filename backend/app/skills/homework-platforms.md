---
name: homework-platforms
description: Working homework on other platforms professors assign -- Cengage MindTap, Macmillan Achieve and Sapling, WileyPLUS, zyBooks, Hawkes Learning, Top Hat, Perusall, Gradescope -- plus Blackboard, Brightspace, Moodle and Google Classroom courses.
keywords: [mindtap, cengage, achieve, macmillan, sapling, wileyplus, wiley plus, zybooks, zybook, hawkes, top hat, tophat, perusall, gradescope, blackboard, brightspace, d2l, moodle, google classroom, homework platform]
---

These platforms are **experimental** in Nova: recognized, handled with the general routine below, not yet run end to end on live assignments. The app's platform list (Settings, Homework platforms) shows each one's status.

## The general routine

1. **Inspect** the assignment and find the platform's frame or tab (`platforms` in the inspect result). If inspect returns a `stop` notice (proctored, lockdown browser, live session), stop and tell the user.
2. **Read the whole question** and any instructions, rubric or attachment before answering.
3. **Work the answer out first.** Use real sources for written answers.
4. **Enter it** by ref: math boxes in calculator notation, choices by clicking the option, text boxes with plain words. Check what each box shows.
5. **Submitting** (Submit, Check, Check Answer, Grade) always goes through `coursework_external_submit` with your reasoning, one question at a time.
6. **Read the result** that appears afterwards and report it honestly: correct, incorrect, partial, or not shown.

## Platform notes

- **Cengage MindTap:** mixes readings and activities; activities are the graded part.
- **Macmillan Achieve and Sapling:** Check Answer is graded, and some problems reduce credit per attempt -- don't guess. Structure drawings: report rather than guess.
- **WileyPLUS:** numeric parts may limit attempts.
- **zyBooks:** participation activities are checked in the page; challenge activities may include code that runs in the page -- test it before submitting.
- **Hawkes Learning:** practice and certify modes; certify is graded.
- **Top Hat:** homework and readings only. Live in-class questions are the student's own; don't answer them.
- **Perusall:** annotations are written work. Draft them for the user to review, the same as discussion posts.
- **Gradescope:** submit only files or answers the user approved, and confirm the receipt afterwards.
- **Blackboard, Brightspace, Moodle, Google Classroom:** Nova can open and read these courses and launch their tools; it cannot list their assignments automatically yet, so ask the user for the assignment link.

## Always stop and tell the user

- Proctored tests, lockdown browsers, live sessions, sign-in or two-factor prompts, and physical or in-person work.
