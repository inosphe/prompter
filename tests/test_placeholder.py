"""Tests for the shared placeholder/merge logic."""

from prompter.placeholder import (
    find_blocks,
    has_block,
    merge,
    render_block,
    slugify,
    strip_blocks,
)


def test_render_block():
    out = render_block("coding-style", "  body text  ")
    assert out == "<!-- prompter:coding-style -->\nbody text\n<!-- /prompter:coding-style -->"


def test_merge_appends_when_absent():
    existing = "# My project\n\nSome notes.\n"
    text, replaced, appended = merge(existing, [("rules", "be nice")])
    assert replaced == []
    assert appended == ["rules"]
    assert "# My project" in text  # preserved
    assert has_block(text, "rules")


def test_merge_replaces_in_place_and_preserves_position():
    existing = (
        "intro\n\n"
        "<!-- prompter:rules -->\nOLD\n<!-- /prompter:rules -->\n\n"
        "trailing content\n"
    )
    text, replaced, appended = merge(existing, [("rules", "NEW")])
    assert replaced == ["rules"]
    assert appended == []
    assert "NEW" in text and "OLD" not in text
    # surrounding content preserved & order kept
    assert text.index("intro") < text.index("NEW") < text.index("trailing content")


def test_merge_handles_regex_special_chars_in_body():
    existing = ""
    body = r"use \1 and $name and (group)"
    text, _, _ = merge(existing, [("tricky", body)])
    assert body in text


def test_merge_mixed_replace_and_append():
    existing = "<!-- prompter:a -->\nA0\n<!-- /prompter:a -->\n"
    text, replaced, appended = merge(existing, [("a", "A1"), ("b", "B1")])
    assert replaced == ["a"]
    assert appended == ["b"]
    assert "A1" in text and "A0" not in text
    assert has_block(text, "b")


def test_find_and_strip_blocks():
    text = "top\n<!-- prompter:x -->\nXX\n<!-- /prompter:x -->\nbottom\n"
    blocks = find_blocks(text)
    assert [b.name for b in blocks] == ["x"]
    assert blocks[0].body == "XX"
    cleaned, removed = strip_blocks(text)
    assert "XX" not in cleaned
    assert "top" in cleaned and "bottom" in cleaned
    assert [b.name for b in removed] == ["x"]


def test_slugify():
    assert slugify("Coding Style!") == "coding-style"
    assert slugify("  Multiple   Spaces  ") == "multiple-spaces"
    assert slugify("???") == "snippet"
