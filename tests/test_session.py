from src.session import Session, State, is_close_phrase, normalize


CLOSE = [
    "that's all friday",
    "thats all friday",
    "thanks friday",
    "thank you friday",
    "fine friday",
    "goodbye friday",
    "bye friday",
    "we're done friday",
    "were done friday",
]


def test_normalize_keeps_apostrophes():
    assert normalize("That's all, Friday!") == "that's all friday"


def test_normalize_collapses_punctuation():
    assert normalize("Hey — Friday. Thanks!") == "hey friday thanks"


def test_empty_transcript_not_close():
    assert not is_close_phrase("", CLOSE)
    assert not is_close_phrase("   ", CLOSE)


def test_exact_close_phrases():
    for p in CLOSE:
        assert is_close_phrase(p, CLOSE), f"failed: {p!r}"


def test_close_embedded_in_longer_utterance():
    assert is_close_phrase("Okay thanks Friday, that was useful", CLOSE)


def test_apostrophe_dropped_variant():
    assert is_close_phrase("thats all friday", CLOSE)


def test_non_close_question_not_matched():
    assert not is_close_phrase("Friday what time is it", CLOSE)
    assert not is_close_phrase("Hey Friday, play Bowie", CLOSE)


def test_session_defaults():
    s = Session()
    assert s.state is State.IDLE
    assert s.turns == []
    assert s.sdk_session_id is None


def test_session_mutable():
    s = Session()
    s.state = State.ACTIVE
    s.turns.append({"user": "hi"})
    assert s.state is State.ACTIVE
    assert len(s.turns) == 1
