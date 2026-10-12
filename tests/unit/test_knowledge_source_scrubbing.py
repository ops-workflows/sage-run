import pytest

from shared.lib.knowledge_source_confluence import normalize_storage, normalized_text
from shared.lib.knowledge_source_scrubbing import compile_scrub_rules, scrub_document

pytestmark = pytest.mark.unit


def test_scrubs_all_body_representations_and_cross_block_matches():
    document = normalize_storage("<h1>secret-123</h1><p>begin token</p><p>end value</p><pre>private\nkey</pre>")
    rules = compile_scrub_rules([r"secret-\d+", r"(?s)token.*?end", r"(?s)private.*key"])
    scrubbed = scrub_document(document, rules)
    assert "secret-123" not in repr(scrubbed)
    assert "token" not in scrubbed.content and "end" not in scrubbed.content
    assert "private" not in scrubbed.content and "key" not in scrubbed.content
    assert scrubbed.blocks[0].heading_path == ("[REDACTED]",)
    assert all(block.heading_path == ("[REDACTED]",) for block in scrubbed.blocks)
    assert scrubbed.content == normalized_text(scrubbed.blocks)


def test_rule_order_flags_and_empty_rules():
    document = normalize_storage("<p>SECRET remains</p>")
    assert scrub_document(document, ()) is document
    assert scrub_document(document, compile_scrub_rules(["secret"])).content == document.content
    assert (
        scrub_document(document, compile_scrub_rules(["", "(?i)secret", r"\[REDACTED\] remains"])).content
        == "[REDACTED]"
    )


@pytest.mark.parametrize("patterns", [["["], ["ok", "("], ["x" * 2001], ["first\nsecond"], ["x"] * 101])
def test_invalid_rules_are_rejected_without_echoing_patterns(patterns):
    with pytest.raises(ValueError):
        compile_scrub_rules(patterns)


def test_timeout_fails_without_returning_unscrubbed_text(monkeypatch):
    monkeypatch.setattr("shared.lib.knowledge_source_scrubbing.SCRUB_TIMEOUT_SEC", 0.001)
    document = normalize_storage("<p>" + "a" * 10000 + "!</p>")
    with pytest.raises(ValueError, match="execution budget"):
        scrub_document(document, compile_scrub_rules(["(a+)+$"]))


def test_nested_heading_paths_follow_redacted_heading_text():
    document = normalize_storage("<h1>parent-secret</h1><h2>child-secret</h2><p>body</p><h1>next</h1><p>tail</p>")
    scrubbed = scrub_document(document, compile_scrub_rules(["parent-secret", "child-secret"]))
    assert scrubbed.blocks[2].heading_path == ("[REDACTED]", "[REDACTED]")
    assert scrubbed.blocks[-1].heading_path == ("next",)
    assert "secret" not in repr(scrubbed)


def test_zero_width_matches_are_bounded_and_preserve_document_consistency():
    document = normalize_storage("<p>first</p><p>second</p>")
    scrubbed = scrub_document(document, compile_scrub_rules(["(?m)^", "$", "(?=second)"]))
    assert "[REDACTED]first" in scrubbed.content
    assert "[REDACTED]second" in scrubbed.content
    assert scrubbed.content == normalized_text(scrubbed.blocks)
