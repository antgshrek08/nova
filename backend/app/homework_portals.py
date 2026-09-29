"""Homework platforms Nova recognizes, and how each one talks.

One registry for every platform a professor may assign work on: how to
recognize it (hosts), the words it uses for a checked answer, an unfinished
attempt and a finished assignment, and what stops Nova (proctoring, lockdown
browsers, live sessions). The autopilot, the external-homework tool and the
support list in the app all read from here.

Status is honest (rebuild plan §5: a platform name alone is not support):
- "tested": worked end to end on a live assignment;
- "experimental": recognized and handled with its own routine, not yet run
  on a live assignment -- Nova reports what it sees instead of assuming;
- "browse": Nova can open and read it, but has no assignment workflow;
- "unsupported": Nova stops and says why (live, proctored, physical work).

Phrase lists are deliberately conservative: a phrase that is missing only
means Nova reads the page instead of trusting a banner; a wrong phrase would
make it claim a result that did not happen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Portal:
    id: str
    name: str
    vendor: str
    kind: str  # "homework" | "lms" | "reading" | "submission" | "live"
    hosts: tuple[str, ...]
    status: str
    routine: str = ""  # skills/<routine>.md, loaded when the user names the platform
    correct: tuple[str, ...] = ()
    incorrect: tuple[str, ...] = ()
    partial: tuple[str, ...] = ()
    complete: tuple[str, ...] = ()
    notes: str = ""
    handles: tuple[str, ...] = field(default=())


GENERIC_CORRECT = (r"\bcorrect[.!]*$", r"^correct\b", r"\bthat'?s (?:right|correct)\b", r"\bwell done\b",
                   r"\banswer accepted\b", r"\bgreat (?:job|work)\b", r"\bnice work\b")
GENERIC_INCORRECT = (r"\bincorrect\b", r"\bnot correct\b", r"\btry again\b", r"\bwrong answer\b", r"\bnot quite\b")
GENERIC_PARTIAL = (r"\bpartially correct\b", r"\bpartial credit\b")
GENERIC_COMPLETE = ("assignment complete", "you have completed this assignment", "all questions completed", "results submitted")

# IMathAS (Lumen OHM, MyOpenMath) reports a numeric score after each try.
IMATHAS_SCORE = re.compile(r"score on last (?:try|attempt)\s*:\s*([\d.]+)\s*(?:out\s+)?of\s*([\d.]+)", re.I)

BLOCKERS = {
    "proctored": ("honorlock", "proctorio", "proctoru", "proctortrack", "examity", "respondus monitor"),
    "lockdown browser": ("lockdown browser", "respondus lockdown", "securexam"),
    "live session": ("join the live session", "waiting for the instructor to start"),
}

PORTALS: tuple[Portal, ...] = (
    Portal("canvas", "Canvas", "Instructure", "lms", ("instructure.com",), "tested",
           notes="Assignment discovery, quizzes, file and text submissions, and launching every tool below.",
           handles=("assignments", "quizzes", "file upload", "text entry", "discussions")),
    Portal("knewton", "Knewton Alta", "Wiley", "homework", ("knewton.com", "knerd.com"), "tested", routine="knewton-alta",
           handles=("math entry", "multiple choice", "graphing", "matching")),
    Portal("mheducation", "McGraw Hill Connect and SmartBook", "McGraw Hill", "homework",
           ("mheducation.com", "connect.mheducation.com", "learning.mheducation.com"), "tested",
           handles=("SmartBook concepts", "multiple choice", "fill in the blank")),
    Portal("pearson", "Pearson MyLab and Mastering", "Pearson", "homework",
           ("mylab.pearson.com", "mathxl.com", "pearsoncmg.com", "pearson.com", "pearsonmylabandmastering.com",
            "masteringphysics.com", "masteringchemistry.com", "masteringbiology.com", "mastering.pearson.com"),
           "experimental", routine="pearson-mylab",
           correct=(r"\bcorrect\b(?! answer is)",), incorrect=(r"\bincorrect\b", r"\btry again\b"),
           partial=(r"\bpartially correct\b",),
           notes="MathXL player math entry, Check Answer, limited attempts per question. Tests and quizzes may be proctored.",
           handles=("math entry", "multiple choice", "fill in the blank", "graphing (reported, not guessed)")),
    Portal("aleks", "ALEKS", "McGraw Hill", "homework", ("aleks.com",), "experimental", routine="aleks",
           correct=(r"\bcorrect\b",), incorrect=(r"\bincorrect\b", r"\btry again\b"),
           notes="Learning mode topics use Check, Explain and Try Again. Knowledge Checks are assessments: Nova stops "
                 "if one is proctored or locked down.",
           handles=("math entry", "multiple choice", "graphing (reported, not guessed)")),
    Portal("lumen", "Lumen Learning (OHM, Waymaker, Lumen One)", "Lumen Learning", "homework",
           ("lumenlearning.com",), "experimental", routine="lumen",
           notes="OHM is built on IMathAS and reports 'Score on last try: X out of Y' after each attempt.",
           handles=("math entry", "multiple choice", "fill in the blank")),
    Portal("myopenmath", "MyOpenMath", "IMathAS", "homework", ("myopenmath.com",), "experimental", routine="lumen",
           notes="Same engine as Lumen OHM.", handles=("math entry", "multiple choice")),
    Portal("webassign", "WebAssign", "Cengage", "homework", ("webassign.net", "webassign.com"), "experimental",
           routine="webassign", incorrect=(r"your response differs from the correct answer",),
           notes="Answers are submitted per question or for the whole assignment; submissions are counted.",
           handles=("math entry", "numeric", "multiple choice")),
    Portal("cengage", "Cengage MindTap", "Cengage", "homework", ("ng.cengage.com", "cengage.com"), "experimental",
           routine="homework-platforms", handles=("readings", "multiple choice", "activities")),
    Portal("macmillan", "Macmillan Achieve and Sapling", "Macmillan Learning", "homework",
           ("achieve.macmillanlearning.com", "macmillanlearning.com", "saplinglearning.com"), "experimental",
           routine="homework-platforms", handles=("math entry", "multiple choice", "chemistry drawing (reported, not guessed)")),
    Portal("wiley", "WileyPLUS", "Wiley", "homework", ("wileyplus.com", "education.wiley.com"), "experimental",
           routine="homework-platforms", handles=("numeric", "multiple choice")),
    Portal("zybooks", "zyBooks", "Wiley", "homework", ("zybooks.com",), "experimental", routine="homework-platforms",
           notes="Participation activities and challenge activities; code challenges run in the page.",
           handles=("participation activities", "challenge activities", "code")),
    Portal("hawkes", "Hawkes Learning", "Hawkes", "homework", ("hawkeslearning.com",), "experimental",
           routine="homework-platforms", handles=("math entry", "multiple choice")),
    Portal("tophat", "Top Hat", "Top Hat", "homework", ("tophat.com",), "experimental", routine="homework-platforms",
           notes="Homework and readings only; live in-class questions are unsupported.", handles=("questions", "readings")),
    Portal("perusall", "Perusall", "Perusall", "reading", ("perusall.com",), "experimental", routine="homework-platforms",
           notes="Annotations are written work: Nova drafts them for your review, like discussion posts.",
           handles=("reading annotations",)),
    Portal("gradescope", "Gradescope", "Turnitin", "submission", ("gradescope.com",), "experimental",
           routine="homework-platforms", notes="File and online assignments; Nova submits only what you approved.",
           handles=("file upload", "online assignments")),
    Portal("blackboard", "Blackboard Learn", "Anthology", "lms", ("blackboard.com", "bbcollab.com"), "browse",
           notes="Nova can open and read courses and launch tools; assignment discovery is Canvas only for now."),
    Portal("brightspace", "D2L Brightspace", "D2L", "lms", ("brightspace.com", "d2l.com", "desire2learn.com"), "browse",
           notes="Nova can open and read courses and launch tools; assignment discovery is Canvas only for now."),
    Portal("moodle", "Moodle", "Moodle", "lms", ("moodle.",), "browse",
           notes="Nova can open and read courses and launch tools; assignment discovery is Canvas only for now."),
    Portal("classroom", "Google Classroom", "Google", "lms", ("classroom.google.com",), "browse",
           notes="Nova can open and read classes; assignment discovery is Canvas only for now."),
    Portal("iclicker", "iClicker", "Macmillan Learning", "live", ("iclicker.com",), "unsupported",
           notes="Live in-class polling; answering for you in class isn't something Nova does."),
    Portal("kahoot", "Kahoot", "Kahoot", "live", ("kahoot.it", "kahoot.com"), "unsupported", notes="Live game sessions."),
)

_BY_ID = {p.id: p for p in PORTALS}


def get(portal_id: str | None) -> Portal | None:
    return _BY_ID.get(portal_id or "")


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.endswith("."):  # a product name that appears in many institutions' hostnames
        return pattern in host
    return host == pattern or host.endswith("." + pattern)


def detect(url: str = "", text: str = "") -> Portal | None:
    """The platform behind a URL, or named in a launch page's text."""
    host = (urlsplit(url).hostname or "").lower()
    if host:
        for portal in PORTALS:
            if any(_host_matches(host, h) for h in portal.hosts):
                return portal
    low = (text or "").lower()[:4000]
    for portal in PORTALS:
        if portal.kind != "lms" and (portal.name.lower() in low or portal.id in low.split()):
            return portal
    return None


def blockers(text: str) -> list[str]:
    """Why Nova must stop on this page (proctoring, lockdown, live)."""
    low = (text or "").lower()
    return [reason for reason, words in BLOCKERS.items() if any(w in low for w in words)]


def _new_lines(before: str, after: str) -> str:
    old = {line.strip().lower() for line in (before or "").splitlines()}
    return "\n".join(line.strip().lower() for line in (after or "").splitlines() if line.strip() and line.strip().lower() not in old)


def feedback(before: str, after: str, portal_id: str | None = None) -> str:
    """"correct" | "incorrect" | "partial" | "unknown", from text that appeared
    after the answer was checked. A banner already on the page before is not
    evidence for this answer."""
    fresh = _new_lines(before, after)
    if not fresh:
        return "unknown"
    score = IMATHAS_SCORE.search(fresh)
    if score:
        got, of = float(score[1]), float(score[2])
        if of > 0:
            return "correct" if got >= of else ("incorrect" if got == 0 else "partial")
    portal = get(portal_id)
    partial = GENERIC_PARTIAL + (portal.partial if portal else ())
    incorrect = GENERIC_INCORRECT + (portal.incorrect if portal else ())
    correct = GENERIC_CORRECT + (portal.correct if portal else ())
    lines = fresh.splitlines()
    if any(re.search(p, fresh, re.M) for p in partial):
        return "partial"
    if any(re.search(p, fresh, re.M) for p in incorrect):
        return "incorrect"
    if any(re.search(p, line) for p in correct for line in lines):
        return "correct"
    return "unknown"


def complete(text: str, portal_id: str | None = None) -> bool:
    phrases = GENERIC_COMPLETE + ((get(portal_id).complete if get(portal_id) else ()))
    return any(line.strip().lower().rstrip(".! ") in phrases for line in (text or "").splitlines())


def describe(portal: Portal | None) -> dict | None:
    if portal is None:
        return None
    return {"id": portal.id, "name": portal.name, "status": portal.status, "routine": portal.routine or None,
            "notes": portal.notes}


def support_matrix() -> list[dict]:
    return [{"id": p.id, "name": p.name, "vendor": p.vendor, "kind": p.kind, "status": p.status,
             "handles": list(p.handles), "notes": p.notes, "routine": p.routine or None} for p in PORTALS]
