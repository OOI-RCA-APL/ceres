"""Docstring splitting. Several cases are drawn from the `docstring_parser` test suite (MIT,
https://github.com/rr-/docstring_parser), the reference the parser was built against."""

from ceres.__internal__.utilities.docstrings import Docstring, DocstringRaise, parse_docstring


def test_missing_or_empty_docstring_is_empty():
    assert parse_docstring(None) == Docstring()
    assert parse_docstring("") == Docstring()
    assert parse_docstring("   \n  ") == Docstring()


def test_prose_is_kept_as_written():
    docstring = parse_docstring(
        """Take a picture.

        The picture is **saved** to disk:

        - one per camera
        - named by time

            indented code stays indented

        Note: prose with a colon is not a field.
        """
    )
    assert docstring.description == (
        "Take a picture.\n\n"
        "The picture is **saved** to disk:\n\n"
        "- one per camera\n"
        "- named by time\n\n"
        "    indented code stays indented\n\n"
        "Note: prose with a colon is not a field."
    )
    assert docstring.params == {}
    assert docstring.returns is None
    assert docstring.raises == ()


def test_google_sections():
    docstring = parse_docstring(
        """Move the stage.

        Args:
            x (float): Where to go along x,
                in millimetres.
            y: Where to go along y.

                A second paragraph about y.
            *args: Extra positions.
            **options (dict, optional): Extra options.

        Returns:
            bool: Whether the stage arrived.

        Raises:
            ValueError: If x is out of range.
            errors.Timeout: If the stage never settles.
        """
    )
    assert docstring.description == "Move the stage."
    assert docstring.params == {
        "x": "Where to go along x,\nin millimetres.",
        "y": "Where to go along y.\n\nA second paragraph about y.",
        "args": "Extra positions.",
        "options": "Extra options.",
    }
    assert docstring.returns == "Whether the stage arrived."
    assert docstring.raises == (
        DocstringRaise(type="ValueError", description="If x is out of range."),
        DocstringRaise(type="errors.Timeout", description="If the stage never settles."),
    )


def test_google_titles_ignore_case_and_aliases():
    docstring = parse_docstring(
        """Summary.

        PARAMETERS:
            a: first
        Keyword Arguments:
            b: second
        Yields:
            The values.
        Exceptions:
            KeyError: missing
        """
    )
    assert docstring.description == "Summary."
    assert docstring.params == {"a": "first", "b": "second"}
    assert docstring.returns == "The values."
    assert docstring.raises == (DocstringRaise(type="KeyError", description="missing"),)


def test_google_return_prose_keeps_its_words():
    docstring = parse_docstring(
        """Summary.

        Returns:
            The count of things: always positive.
        """
    )
    assert docstring.returns == "The count of things: always positive."


def test_google_unknown_section_stays_in_the_prose():
    docstring = parse_docstring(
        """
        Unknown:
            spam: a
        """
    )
    assert docstring.description == "Unknown:\n    spam: a"
    assert docstring.params == {}


def test_google_section_title_without_body_stays_in_the_prose():
    docstring = parse_docstring("Summary.\n\nReturns:\nnothing indented here.")
    assert docstring.description == "Summary.\n\nReturns:\nnothing indented here."
    assert docstring.returns is None


def test_google_prose_after_a_section_is_kept():
    docstring = parse_docstring(
        """Summary.

        Args:
            a: first

        Example:
            run(a=1)
        """
    )
    assert docstring.params == {"a": "first"}
    assert docstring.description == "Summary.\n\nExample:\n    run(a=1)"


def test_google_type_wrapping_onto_the_next_line():
    docstring = parse_docstring(
        """Description of the function.

        Args:
            output_type (Literal["searchResults", "sourcedAnswer",
                "structured"]): The type of output.
                This can be one of the following:
                - "searchResults": Represents the search results.
                - "structured": Represents a structured output format.

        Returns:
            bool: Indicates success or failure.
        """
    )
    assert docstring.params == {
        "output_type": (
            "The type of output.\nThis can be one of the following:\n"
            '- "searchResults": Represents the search results.\n'
            '- "structured": Represents a structured output format.'
        )
    }
    assert docstring.returns == "Indicates success or failure."


def test_google_entry_line_that_is_not_an_entry_continues_the_last():
    docstring = parse_docstring(
        """Summary.

        Args:
            a: first
            and more about a
        """
    )
    assert docstring.params == {"a": "first\nand more about a"}


def test_sphinx_fields():
    docstring = parse_docstring(
        """Turn the lasers on or off.

        Corresponds to `/api/expansion/{on|off}/3`.

        :param on: `True` to turn the lasers on,
            and `False` to turn them off.
        :type on: bool
        :param int level: Brightness.
        :keyword fast: Skip the ramp.
        :returns: Whether it worked.
        :rtype: bool
        :raises ValueError: If the level is out of range.
        :raises: When anything else goes wrong.
        """
    )
    assert docstring.description == (
        "Turn the lasers on or off.\n\nCorresponds to `/api/expansion/{on|off}/3`."
    )
    assert docstring.params == {
        "on": "`True` to turn the lasers on,\nand `False` to turn them off.",
        "level": "Brightness.",
        "fast": "Skip the ramp.",
    }
    assert docstring.returns == "Whether it worked."
    assert docstring.raises == (
        DocstringRaise(type="ValueError", description="If the level is out of range."),
        DocstringRaise(type=None, description="When anything else goes wrong."),
    )


def test_sphinx_field_text_on_the_next_line():
    docstring = parse_docstring(
        """Summary.

        :param a:
            On its own line.
        :return:
            Something.
        """
    )
    assert docstring.params == {"a": "On its own line."}
    assert docstring.returns == "Something."


def test_line_starting_with_a_colon_that_is_no_field_is_prose():
    docstring = parse_docstring("Summary.\n\n:) smile\n:unknown thing: here")
    assert docstring.description == "Summary.\n\n:) smile\n:unknown thing: here"


def test_styles_mix_and_the_first_text_for_a_name_wins():
    docstring = parse_docstring(
        """Summary.

        Args:
            a: from Google

        :param a: from Sphinx
        :param b: only Sphinx
        """
    )
    assert docstring.description == "Summary."
    assert docstring.params == {"a": "from Google", "b": "only Sphinx"}
