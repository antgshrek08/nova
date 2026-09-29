import pytest

from app import coursework_autopilot as pilot, homework_portals as hp, skills


@pytest.mark.parametrize("url,expected", [
    ("https://mylab.pearson.com/Student/PlayerHomework.aspx", "pearson"),
    ("https://xlitemprod.pearsoncmg.com/api/v1/print", "pearson"),
    ("https://session.masteringphysics.com/myct/assignments", "pearson"),
    ("https://www-awu.aleks.com/alekscgi/x/Isl.exe", "aleks"),
    ("https://ohm.lumenlearning.com/assess2/?cid=1", "lumen"),
    ("https://waymaker.lumenlearning.com/course", "lumen"),
    ("https://www.myopenmath.com/assess2/", "myopenmath"),
    ("https://www.webassign.net/web/Student/Assignment-Responses/", "webassign"),
    ("https://ng.cengage.com/static/nb/ui/", "cengage"),
    ("https://achieve.macmillanlearning.com/courses/1", "macmillan"),
    ("https://learn.zybooks.com/zybook/X", "zybooks"),
    ("https://app.tophat.com/e/1", "tophat"),
    ("https://app.perusall.com/courses/x", "perusall"),
    ("https://www.gradescope.com/courses/1", "gradescope"),
    ("https://www.knewton.com/x", "knewton"),
    ("https://learning.mheducation.com/static/awd", "mheducation"),
    ("https://elearn.moodle.school.edu/course", "moodle"),
    ("https://school.instructure.com/courses/1/assignments/2", "canvas"),
])
def test_platforms_are_recognized_by_host(url, expected):
    assert hp.detect(url).id == expected


def test_lookalike_hosts_are_not_trusted():
    assert hp.detect("https://pearson.com.evil.test/login") is None
    assert hp.detect("https://notaleks.com/") is None


def test_autopilot_keeps_canvas_page_types():
    assert pilot._detect_portal_type("https://x.instructure.com/courses/1/quizzes/2") == "canvas_quiz"
    assert pilot._detect_portal_type("https://x.instructure.com/courses/1/assignments/2") == "canvas_generic"
    assert pilot._detect_portal_type("https://mylab.pearson.com/x") == "pearson"
    assert pilot._detect_portal_type("https://x.test/", "Ch 7 SmartBook assignment") == "mheducation"


@pytest.mark.parametrize("before,after,portal,expected", [
    ("Question 3", "Great work! That's correct.", "knewton", "correct"),
    ("Question 3", "Your answer is correct", None, "correct"),
    ("Question 3", "The correct answer is 5", None, "unknown"),
    ("Question 3", "Incorrect. Try again.", "pearson", "incorrect"),
    ("Question 3", "Partially correct", "pearson", "partial"),
    ("Q", "Score on last try: 1 out of 1", "lumen", "correct"),
    ("Q", "Score on last try: 0 out of 1", "lumen", "incorrect"),
    ("Q", "Score on last try: 0.5 out of 1", "myopenmath", "partial"),
    ("Q", "Your response differs from the correct answer by more than 10%.", "webassign", "incorrect"),
    ("Correct! earlier banner", "Correct! earlier banner", "aleks", "unknown"),
])
def test_feedback_uses_only_new_text_and_each_platforms_words(before, after, portal, expected):
    assert pilot.classify_feedback(before, after, portal) == expected


def test_stop_conditions():
    assert hp.blockers("This quiz requires Respondus LockDown Browser") == ["lockdown browser"]
    assert hp.blockers("Proctored by Honorlock") == ["proctored"]
    assert hp.blockers("Question 1 of 10") == []


def test_completion_phrases():
    assert pilot.assignment_complete("Assignment complete!", "aleks")
    assert not pilot.assignment_complete("Complete the assignment by Friday", "aleks")


def test_support_matrix_is_honest():
    rows = {r["id"]: r for r in hp.support_matrix()}
    assert {rows[i]["status"] for i in ("canvas", "knewton", "mheducation")} == {"tested"}
    assert {rows[i]["status"] for i in ("pearson", "aleks", "lumen", "webassign")} == {"experimental"}
    assert rows["iclicker"]["status"] == "unsupported"
    assert rows["blackboard"]["status"] == "browse"


@pytest.mark.parametrize("message,routine", [
    ("do my pearson mylab homework", "pearson-mylab"),
    ("finish my aleks topics", "aleks"),
    ("work through my lumen ohm assignment", "lumen"),
    ("do the webassign problems", "webassign"),
    ("help with my zybooks activities", "homework-platforms"),
])
def test_each_platform_routine_is_picked(message, routine):
    assert routine in [s.name for s in skills.select_relevant_skills(message)]
