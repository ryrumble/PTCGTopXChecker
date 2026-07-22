"""Comprehensive tests for parsers: Format A, Format B, and detection."""

from parsers import (
    ParsedEntry,
    detect_format,
    parse_format_a,
    parse_format_b,
    to_normalized_entries,
)


class TestDetectFormat:
    def test_empty_input_defaults_to_a(self):
        assert detect_format("") == "A"

    def test_only_blank_lines_defaults_to_a(self):
        assert detect_format("  \n  \n  ") == "A"

    def test_numbered_line_detects_a(self):
        text = "1. Tord Reklev [NO]"
        assert detect_format(text) == "A"

    def test_numbered_line_with_parenthesis_detects_a(self):
        text = "1) Name"
        assert detect_format(text) == "A"

    def test_scoreboard_line_detects_b(self):
        text = "# Name    Points"
        assert detect_format(text) == "B"

    def test_plain_text_detects_b(self):
        text = "Hello world"
        assert detect_format(text) == "B"


class TestParseFormatA:
    def test_simple_names_with_region(self):
        text = "1. Tord Reklev [NO]\n2. Liam Halliburton [US]"
        entries = parse_format_a(text)
        assert len(entries) == 2
        assert entries[0] == ParsedEntry(placement=1, raw_name="Tord Reklev", region_code="NO")
        assert entries[1] == ParsedEntry(placement=2, raw_name="Liam Halliburton", region_code="US")

    def test_names_without_region(self):
        text = "1. Tord Reklev\n2. Liam Halliburton"
        entries = parse_format_a(text)
        assert len(entries) == 2
        assert entries[0].region_code is None
        assert entries[1].region_code is None

    def test_parenthesis_separator(self):
        text = "1) Name [US]"
        entries = parse_format_a(text)
        assert len(entries) == 1
        assert entries[0].placement == 1
        assert entries[0].region_code == "US"

    def test_extra_whitespace(self):
        text = "  1.  Name  [US]  "
        entries = parse_format_a(text)
        assert len(entries) == 1
        assert entries[0].placement == 1
        assert entries[0].raw_name == "Name"

    def test_empty_lines_skipped(self):
        text = "1. First [US]\n\n2. Second [CA]\n  \n3. Third [MX]"
        entries = parse_format_a(text)
        assert len(entries) == 3

    def test_unparseable_lines_logged_and_skipped(self):
        text = "1. Valid [US]\nnot a number line\n3. Valid [CA]"
        entries = parse_format_a(text)
        assert len(entries) == 2

    def test_unicode_names(self):
        text = "1. José García [ES]\n2. Łukasz Kowalski [PL]"
        entries = parse_format_a(text)
        assert len(entries) == 2
        assert entries[0].raw_name == "José García"

    def test_two_letter_region_codes(self):
        text = "1. Name [US]\n2. Name2 [GB]"
        entries = parse_format_a(text)
        assert entries[0].region_code == "US"
        assert entries[1].region_code == "GB"

    def test_three_letter_region_codes(self):
        text = "1. Name [USA]"
        entries = parse_format_a(text)
        assert entries[0].region_code == "USA"

    def test_region_code_case_insensitivity(self):
        text = "1. Name [us]\n2. Name2 [Gb]"
        entries = parse_format_a(text)
        assert entries[0].region_code == "us"
        assert entries[1].region_code == "Gb"

    def test_empty_text(self):
        assert parse_format_a("") == []


class TestParseFormatB:
    def test_standard_scoreboard(self):
        text = """# Name    Points
1
Eduardo Molina
CL
38  12 - 1 - 2
2
Denis Provázek
CZ
34  10 - 1 - 4
"""
        entries = parse_format_b(text)
        assert len(entries) == 2
        assert entries[0] == ParsedEntry(placement=1, raw_name="Eduardo Molina", region_code="CL")
        assert entries[1] == ParsedEntry(placement=2, raw_name="Denis Provázek", region_code="CZ")

    def test_missing_region_line(self):
        text = """# Name
1
Player Name
38  12 - 1 - 2
"""
        entries = parse_format_b(text)
        assert len(entries) == 1
        assert entries[0].placement == 1
        assert entries[0].region_code is None

    def test_header_variations(self):
        text = """Rank	Name	Points	Record
1
Player Name
US
100	10-0
"""
        entries = parse_format_b(text)
        assert len(entries) == 1
        assert entries[0].region_code == "US"

    def test_trailing_blank_lines(self):
        text = "1\nName\nUS\n100\n\n\n"
        entries = parse_format_b(text)
        assert len(entries) == 1

    def test_no_header(self):
        text = "1\nName\nUS\n100"
        entries = parse_format_b(text)
        assert len(entries) == 1

    def test_missing_stats_line(self):
        text = "1\nName\nUS"
        entries = parse_format_b(text)
        assert len(entries) == 1
        assert entries[0].placement == 1
        assert entries[0].region_code == "US"

    def test_region_looks_like_name_but_two_letters(self):
        text = "1\nJo\nUS\n100"
        entries = parse_format_b(text)
        assert len(entries) == 1
        assert entries[0].raw_name == "Jo"
        assert entries[0].region_code == "US"

    def test_line_starting_with_hash_is_skipped(self):
        text = "# Comment line\n1\nName\nUS\n100"
        entries = parse_format_b(text)
        assert len(entries) == 1

    def test_empty_text(self):
        assert parse_format_b("") == []

    def test_no_valid_placement_lines(self):
        text = "Header line\nName\nUS\n100"
        entries = parse_format_b(text)
        assert entries == []

    def test_placement_without_following_name(self):
        text = "1"
        entries = parse_format_b(text)
        assert entries == []


class TestToNormalizedEntries:
    def test_basic_conversion(self):
        parsed = [
            ParsedEntry(placement=1, raw_name="Tord Reklev [NO]", region_code="NO"),
            ParsedEntry(placement=2, raw_name="Liam Halliburton [US]", region_code="US"),
        ]
        result = to_normalized_entries(parsed)
        assert len(result) == 2
        assert result[0] == (1, "Tord Reklev", "NO")
        assert result[1] == (2, "Liam Halliburton", "US")

    def test_empty_input(self):
        assert to_normalized_entries([]) == []

    def test_none_region_preserved(self):
        parsed = [ParsedEntry(placement=1, raw_name="Name", region_code=None)]
        result = to_normalized_entries(parsed)
        assert result[0][2] is None
