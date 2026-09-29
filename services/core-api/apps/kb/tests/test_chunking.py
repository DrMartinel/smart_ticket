"""
Chunking of KB article bodies. The demo KB is AWS documentation in
Markdown, where a page runs to many sections. What matters is that chunk
boundaries follow the document's structure: a chunk records the heading it
sits under, and a code sample is never split or mistaken for a heading.
"""

from apps.kb.utils import CHUNK_TARGET_TOKENS, chunk_body, chunk_sections, clean_markdown

PAGE = """# Troubleshoot SSH

Check the instance first.

## Connection timed out

The security group must allow port 22.

```bash
# this is a shell comment, not a heading

sudo systemctl restart sshd
```

## Permission denied

Use the right key pair.
"""


def test_each_chunk_records_its_section_heading():
    chunks = chunk_sections(PAGE)

    assert [c.section_title for c in chunks] == [
        "Troubleshoot SSH",
        "Connection timed out",
        "Permission denied",
    ]
    assert chunks[2].content == "## Permission denied\n\nUse the right key pair."


def test_a_hash_line_inside_a_code_block_is_not_a_heading_and_the_block_stays_whole():
    """A `#` comment in a shell sample would otherwise start a new section,
    and a blank line inside the fence would split the sample in two."""
    [timed_out] = [c for c in chunk_sections(PAGE) if c.section_title == "Connection timed out"]

    assert "# this is a shell comment, not a heading\n\nsudo systemctl restart sshd" in (
        timed_out.content
    )


def test_a_body_without_headings_chunks_exactly_as_before():
    """Articles created through the API are plain text. Heading-aware
    chunking must not change how they are split."""
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))

    chunks = chunk_sections(body)

    assert [c.content for c in chunks] == chunk_body(body)
    assert all(c.section_title is None for c in chunks)
    assert all(len(c.content.split()) <= CHUNK_TARGET_TOKENS + 62 for c in chunks)


def test_clean_markdown_drops_anchor_lines_and_keeps_the_rest_verbatim():
    raw = '\n\n# What is IAM?\n<a name="introduction"></a>\n\nIAM is a *web service*.\n'

    assert clean_markdown(raw) == "# What is IAM?\n\nIAM is a *web service*."


def test_a_table_longer_than_the_target_is_split_between_rows():
    """A Markdown table has no blank lines, so it used to become one chunk
    however long it was. AWS reference tables run past 300,000 characters,
    beyond the embedder's context, and `load_demo_kb` stopped on the first
    one with a 502 from `/v1/embed`. Rows must stay whole and in order."""
    rows = [f"| iam:Action{i} | " + "description " * 20 + "|" for i in range(60)]
    table = "\n".join(["| Action | Description |", "| --- | --- |", *rows])

    chunks = chunk_sections(f"# Actions\n\n{table}")

    assert len(chunks) > 1
    assert all(len(c.content.split()) <= CHUNK_TARGET_TOKENS for c in chunks)
    kept = [line for c in chunks for line in c.content.splitlines() if line.startswith("| iam:")]
    assert kept == rows


def test_a_single_line_longer_than_the_target_is_split_into_word_windows():
    """One line of the IAM docs is 27,000+ characters. With no line break to
    split at, it is cut into windows of at most the target, losing no word."""
    words = [f"word{i}" for i in range(CHUNK_TARGET_TOKENS * 3 + 7)]

    chunks = chunk_body(" ".join(words))

    assert len(chunks) == 4
    assert all(len(c.split()) <= CHUNK_TARGET_TOKENS for c in chunks)
    assert " ".join(chunks).split() == words
