from app import routing


def test_homework_requests_are_recognised():
    for message in ["do my calculus homework 3.3c", "Open canvas and finish 3.3c to 100% mastery",
                    "help me with this essay", "what is due in my classes this week", "quiz me for the knewton quiz"]:
        assert routing.is_homework(message), message


def test_everything_else_is_left_alone():
    for message in ["write me a poem about rain", "what time is it", "the alternate route home", "close discord", "Refactor this Python class", "Explain guitar mastery"]:
        assert not routing.is_homework(message), message


def test_homework_mode_counts_even_without_the_words():
    assert routing.is_homework("what's the next step?", homework_mode=True)


def test_driving_onyx_still_counts_as_homework(): # the user: "i want it to go to token harbor"
    for message in [
        "3.3b is open on onyx. continue doing that homework until 100%",
        "keep going on the assignment",
        "onyx has 3.3c open, finish the canvas quiz",
    ]:
        assert routing.is_homework(message), message


def test_homework_has_its_own_category_with_a_fallback_chain():
    assert routing.HOMEWORK_CATEGORY in routing.CATEGORY_CHAINS
    chain = routing.CATEGORY_CHAINS[routing.HOMEWORK_CATEGORY]
    assert chain[:-1] == routing.CATEGORY_CHAINS["reasoning_math"]


def test_homework_chain_ends_on_claude_so_a_stuck_run_still_finishes():
    # found live: Token Harbor's DeepSeek spun 24 browser_act calls with zero
    # narration on a Canvas task and gave up -- Claude closes the chain so
    # that kind of task still gets done, not just cheaply attempted.
    chain = routing.CATEGORY_CHAINS[routing.HOMEWORK_CATEGORY]
    assert chain[-1].provider == "claude_cli"
    # reasoning_math itself must be untouched by building the homework chain.
    assert routing.CATEGORY_CHAINS["reasoning_math"][-1].provider != "claude_cli"
