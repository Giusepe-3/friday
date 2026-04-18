from src import personality


def test_placeholders_filled():
    prompt = personality.build(today="2026-04-18", memory="m1 body", facts="f1 body")
    assert "2026-04-18" in prompt
    assert "m1 body" in prompt
    assert "f1 body" in prompt
    assert "FRIDAY" in prompt


def test_empty_memory_defaults():
    prompt = personality.build(today="2026-04-18", memory="", facts="")
    assert "(no recent memory)" in prompt
    assert "(no standing facts)" in prompt


def test_whitespace_only_defaults():
    prompt = personality.build(today="2026-04-18", memory="   \n", facts="\t")
    assert "(no recent memory)" in prompt
    assert "(no standing facts)" in prompt
