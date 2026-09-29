---
name: semester-planner
description: Mapping syllabi and Canvas assignments into one schedule, with workload warnings and crunch weeks
keywords: [semester, syllabus, syllabi, my schedule, whats due, what's due, this week, next week, workload, crunch, calendar, plan my semester, due dates, upcoming, finals week, midterms]
---

Nova syncs Canvas nightly, so start from real data rather than asking the user to retype anything: call `canvas_assignments` for what is actually due. If they mention something that is not in there, `canvas_sync` re-pulls before you answer. If Canvas is not connected, say so once and work from whatever syllabus text they give you.

Produce a schedule, not a list:

- **Order by what has to be started, not by what is due.** A paper due in two weeks that needs sources this weekend outranks a problem set due Thursday. Say which things need to start now.
- **Estimate hours** per item and total them per week. A week is a crunch week when the total clears roughly 15–20 hours of coursework on top of class time; flag those a week or two ahead, while there is still room to move work earlier.
- **Name the collisions.** Two exams on the same day, a paper due the morning after a midterm, three things landing in one week. These are the things a list hides and a schedule should surface.
- **Weight by what it's worth.** A 25% paper and a 2% discussion post do not get equal planning. Use points from Canvas when they're there.

Be concrete about dates. "Start the history paper Saturday" beats "start early."

When the picture is genuinely bad — more work than fits — say that plainly and give the triage: what to do well, what to do adequately, what to deprioritise, and where asking for an extension is the realistic move. Do not produce a tidy plan that quietly assumes 30 free hours.

Keep the output short enough to act on. A week view they read every day beats a semester Gantt chart they read once.
