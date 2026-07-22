"""Tests for utility functions: name normalization, region mapping, slugs, etc."""



from utils import (
    KNOWN_REGION_CODES,
    REGION_DISPLAY_NAMES,
    REGION_GROUPS,
    WORLDS_CUTOFF_BY_REGION,
    TournamentKey,
    extract_region_from_brackets,
    map_region_to_group,
    normalize_player_name,
    slugify,
    timestamp_str,
)


class TestNormalizePlayerName:
    def test_basic_title_case(self):
        assert normalize_player_name("RYUKI OKADA") == "Ryuki Okada"

    def test_strips_region_marker(self):
        assert normalize_player_name("Tord Reklev [NO]") == "Tord Reklev"
        assert normalize_player_name("Liam Halliburton [US]") == "Liam Halliburton"

    def test_strips_three_letter_region_marker(self):
        assert normalize_player_name("Name [USA]") == "Name"

    def test_collapses_whitespace(self):
        assert normalize_player_name("  Name   Surname  ") == "Name Surname"

    def test_unicode_normalization(self):
        result = normalize_player_name("JOSÉ GARCÍA")
        assert result == "José García"

    def test_empty_string(self):
        assert normalize_player_name("") == ""

    def test_whitespace_only(self):
        assert normalize_player_name("   ") == ""

    def test_name_with_multiple_brackets(self):
        result = normalize_player_name("Name [US] [CA]")
        assert result == "Name [Us]"

    def test_dotted_name_preserved(self):
        assert normalize_player_name("Dr. Strange") == "Dr. Strange"


class TestExtractRegionFromBrackets:
    def test_extracts_two_letter_code(self):
        assert extract_region_from_brackets("Name [US]") == "US"

    def test_extracts_three_letter_code(self):
        assert extract_region_from_brackets("Name [USA]") == "USA"

    def test_no_brackets(self):
        assert extract_region_from_brackets("Name") is None

    def test_empty_input(self):
        assert extract_region_from_brackets("") is None

    def test_brackets_in_middle_not_at_end(self):
        assert extract_region_from_brackets("[US] Name") is None

    def test_case_insensitive_returns_uppercase(self):
        assert extract_region_from_brackets("Name [us]") == "US"


class TestMapRegionToGroup:
    def test_na_codes(self):
        for code in ("US", "CA", "PR"):
            assert map_region_to_group(code) == "NA"

    def test_eu_codes(self):
        for code in ("GB", "FR", "DE", "ES", "IT", "PL", "NL", "DK", "SE"):
            assert map_region_to_group(code) == "EU"

    def test_la_codes(self):
        for code in ("CL", "BR", "MX", "PE", "AR", "CO"):
            assert map_region_to_group(code) == "LA"

    def test_oc_codes(self):
        assert map_region_to_group("AU") == "OC"
        assert map_region_to_group("NZ") == "OC"

    def test_mea_codes(self):
        for code in ("IL", "ZA", "QA", "AE", "KW"):
            assert map_region_to_group(code) == "MEA"

    def test_unknown_code_returns_other(self):
        assert map_region_to_group("JP") == "OTHER"
        assert map_region_to_group("XX") == "OTHER"

    def test_none_returns_other(self):
        assert map_region_to_group(None) == "OTHER"

    def test_empty_string_returns_other(self):
        assert map_region_to_group("") == "OTHER"

    def test_case_insensitive(self):
        assert map_region_to_group("us") == "NA"
        assert map_region_to_group("Us") == "NA"


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("Hello! World? #2024") == "hello-world-2024"

    def test_multiple_spaces_and_dashes(self):
        assert slugify("Hello   World---Test") == "hello-world-test"

    def test_leading_trailing_dashes(self):
        assert slugify("--Hello World--") == "hello-world"

    def test_unicode_accents_stripped(self):
        result = slugify("José García")
        # Accents are normalized by NFKC, then non-[a-z0-9] chars are replaced
        assert result == "jos-garc-a"

    def test_empty_string_returns_default(self):
        assert slugify("") == "tournament"

    def test_only_special_chars_returns_default(self):
        assert slugify("!!!") == "tournament"


class TestTimestampStr:
    def test_format(self):
        result = timestamp_str()
        assert len(result) == 14
        assert result.isdigit()

    def test_monotonic(self):
        ts1 = timestamp_str()
        ts2 = timestamp_str()
        assert ts2 >= ts1


class TestRegionConstants:
    def test_known_region_codes_contains_all_group_codes(self):
        for group, codes in REGION_GROUPS.items():
            for code in codes:
                assert code in KNOWN_REGION_CODES, f"{code} from {group} not in KNOWN_REGION_CODES"

    def test_worlds_cutoff_values_are_positive(self):
        for region, cutoff in WORLDS_CUTOFF_BY_REGION.items():
            assert cutoff > 0, f"{region} has non-positive cutoff {cutoff}"

    def test_region_display_names_covers_all_groups(self):
        for group in REGION_GROUPS:
            assert group in REGION_DISPLAY_NAMES, f"{group} missing from REGION_DISPLAY_NAMES"



class TestTournamentKey:
    def test_to_id_basic(self):
        key = TournamentKey(title_norm="Online Regional", url="https://example.com", season="2025-2026")
        result = key.to_id()
        assert "online-regional" in result
        assert "2025-2026" in result

    def test_to_id_without_url(self):
        key = TournamentKey(title_norm="Test Tournament", url="", season="2025-2026")
        result = key.to_id()
        assert "no-url" in result

    def test_to_id_uniqueness(self):
        key1 = TournamentKey(title_norm="Regional A", url="url1", season="2025-2026")
        key2 = TournamentKey(title_norm="Regional B", url="url2", season="2025-2026")
        assert key1.to_id() != key2.to_id()

    def test_to_id_same_tournament_matches(self):
        key1 = TournamentKey(title_norm="Regional", url="url", season="2025-2026")
        key2 = TournamentKey(title_norm="Regional", url="url", season="2025-2026")
        assert key1.to_id() == key2.to_id()

    def test_empty_title_defaults(self):
        key = TournamentKey(title_norm="", url="", season="2025-2026")
        result = key.to_id()
        assert "tournament" in result
