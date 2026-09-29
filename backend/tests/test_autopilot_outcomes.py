import asyncio
from unittest.mock import AsyncMock, patch
from app import coursework_autopilot as pilot, coursework_learner as learner


def test_feedback_does_not_invent_success():
    assert pilot.classify_feedback('Question 2', 'Question 2') == 'unknown'
    assert pilot.classify_feedback('Correct! Previous answer', 'Correct! Previous answer') == 'unknown'
    assert pilot.classify_feedback('Question 2', 'Your answer is incorrect') == 'incorrect'
    assert pilot.classify_feedback('Question 2', 'Your answer is correct') == 'correct'
    assert pilot.classify_feedback('', 'Not correct') == 'incorrect'


def test_queue_reports_processed_separately_from_completed():
    with patch.object(pilot, 'get_course_assignments', AsyncMock(return_value=[{'url': 'https://example.test/1'}])), patch.object(
        pilot, 'run_autopilot_assignment', AsyncMock(return_value={'status': 'attempted', 'questions_solved': 0})
    ), patch.object(pilot.asyncio, 'sleep', AsyncMock()):
        result = asyncio.run(pilot.run_autopilot_queue())
    assert not result['ok']
    assert result['total_assignments_completed'] == 0


def test_no_geometry_is_invented():
    for question in ['draw a parabola', 'draw a circle', 'plot the graph shown', 'shade the solution']:
        assert learner.derive_mathematical_geometry(question, [])['curve_type'] == 'unknown'


def test_asymmetric_graph_axes():
    assert learner.data_to_pixel({'x': 100, 'y': 200, 'width': 300, 'height': 200}, 0, 0, (0, 30), (0, 20)) == (100, 400)


def test_quadratic_constant_is_not_mistaken_for_linear_coefficient():
    assert learner.derive_mathematical_geometry('Graph y = x^2 + 3', [])['points'] == [(0, 3), (1, 4)]
    assert learner.derive_mathematical_geometry('Graph y = (x - 2)^2 + 3', [])['points'] == [(2, 3), (3, 4)]
    assert learner.derive_mathematical_geometry('Graph y = x^3', [])['curve_type'] == 'unknown'


def test_conceptual_solver_uses_configured_homework_routing():
    from app import providers, routing
    with patch.object(pilot.db, 'get_app_settings', AsyncMock(return_value={'prefer_local': True})), patch.object(
        routing, 'resolve', AsyncMock(return_value='local-route')
    ) as resolve, patch.object(providers, 'run_model_call', AsyncMock(return_value='{"answer":"Option B"}')) as model:
        result = asyncio.run(pilot.solve_conceptual_question('Question', ['Option A', 'Option B']))
    assert result['success']
    assert result['answer'] == 'Option B'
    resolve.assert_awaited_once_with(routing.HOMEWORK_CATEGORY, prefer_local=True)
    assert model.call_args.args[0] == 'local-route'


def test_conceptual_solver_does_not_invent_answer_on_provider_failure():
    from app import routing
    with patch.object(pilot.db, 'get_app_settings', AsyncMock(return_value={})), patch.object(
        routing, 'resolve', AsyncMock(side_effect=RuntimeError('unavailable'))
    ):
        result = asyncio.run(pilot.solve_conceptual_question('Question', ['A', 'B']))
    assert result['success'] is False
    assert result['answer'] == ''
