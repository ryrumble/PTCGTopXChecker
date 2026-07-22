"""Comprehensive tests for Championship Points calculation logic."""

from cp_calculator import (
    IC_BRACKETS,
    REGIONAL_BRACKETS,
    CPBracket,
    calculate_cp,
)


class TestCPBracket:
    def test_matches_within_range(self):
        b = CPBracket(1, 4, 8, 300)
        assert b.matches(1, 10) is True
        assert b.matches(4, 10) is True

    def test_matches_outside_range(self):
        b = CPBracket(1, 4, 8, 300)
        assert b.matches(5, 10) is False
        assert b.matches(0, 10) is False

    def test_matches_insufficient_competitors(self):
        b = CPBracket(1, 4, 8, 300)
        assert b.matches(1, 5) is False

    def test_matches_exactly_at_kicker(self):
        b = CPBracket(9, 16, 33, 300)
        assert b.matches(9, 33) is True
        assert b.matches(9, 32) is False


class TestICBrackets:
    def test_covers_expected_placements(self):
        assert IC_BRACKETS[0] == CPBracket(1, 1, 0, 500)
        assert IC_BRACKETS[-1] == CPBracket(513, 1_024, 2_049, 40)

    def test_all_brackets_have_increasing_kickers(self):
        for i in range(len(IC_BRACKETS) - 1):
            assert IC_BRACKETS[i].kicker < IC_BRACKETS[i + 1].kicker, (
                f"Bracket {i} kicker {IC_BRACKETS[i].kicker} >= bracket {i + 1} kicker {IC_BRACKETS[i + 1].kicker}"
            )

    def test_all_brackets_have_increasing_max_place(self):
        for i in range(len(IC_BRACKETS) - 1):
            assert IC_BRACKETS[i].max_place < IC_BRACKETS[i + 1].max_place


class TestRegionalBrackets:
    def test_covers_expected_placements(self):
        assert REGIONAL_BRACKETS[0] == CPBracket(1, 1, 0, 350)
        assert REGIONAL_BRACKETS[-1] == CPBracket(513, 1_024, 2_049, 20)

    def test_all_brackets_have_increasing_kickers(self):
        for i in range(len(REGIONAL_BRACKETS) - 1):
            assert REGIONAL_BRACKETS[i].kicker < REGIONAL_BRACKETS[i + 1].kicker

    def test_all_brackets_have_increasing_max_place(self):
        for i in range(len(REGIONAL_BRACKETS) - 1):
            assert REGIONAL_BRACKETS[i].max_place < REGIONAL_BRACKETS[i + 1].max_place


class TestCalculateCP:
    def test_regional_winner(self):
        assert calculate_cp("REGIONAL", 1, 100) == 350
        assert calculate_cp("REGIONAL", 1, 8) == 350
        assert calculate_cp("REGIONAL", 1, 4) == 350

    def test_regional_second(self):
        assert calculate_cp("REGIONAL", 2, 10) == 325
        assert calculate_cp("REGIONAL", 2, 4) == 325

    def test_regional_third_fourth(self):
        assert calculate_cp("REGIONAL", 3, 10) == 300
        assert calculate_cp("REGIONAL", 4, 10) == 300
        assert calculate_cp("REGIONAL", 3, 8) == 300

    def test_regional_insufficient_competitors(self):
        assert calculate_cp("REGIONAL", 3, 7) == 0

    def test_regional_mid_field(self):
        assert calculate_cp("REGIONAL", 70, 260) == 80
        assert calculate_cp("REGIONAL", 100, 300) == 80
        assert calculate_cp("REGIONAL", 128, 300) == 80

    def test_regional_large_event(self):
        assert calculate_cp("REGIONAL", 500, 2_000) == 40
        assert calculate_cp("REGIONAL", 1_000, 3_000) == 20

    def test_ic_winner(self):
        assert calculate_cp("IC", 1, 500) == 500
        assert calculate_cp("IC", 1, 4) == 500

    def test_ic_second(self):
        assert calculate_cp("IC", 2, 10) == 480

    def test_ic_top_4(self):
        assert calculate_cp("IC", 3, 50) == 420
        assert calculate_cp("IC", 4, 50) == 420

    def test_ic_mid_field(self):
        assert calculate_cp("IC", 70, 300) == 140
        assert calculate_cp("IC", 100, 500) == 140

    def test_ic_large_event(self):
        assert calculate_cp("IC", 500, 2_000) == 80
        assert calculate_cp("IC", 1_000, 3_000) == 40

    def test_case_insensitive_type(self):
        assert calculate_cp("regional", 1, 100) == 350
        assert calculate_cp("Regional", 1, 100) == 350
        assert calculate_cp("ic", 1, 500) == 500
        assert calculate_cp("Ic", 1, 500) == 500

    def test_edge_case_placement_zero(self):
        assert calculate_cp("REGIONAL", 0, 100) == 0

    def test_edge_case_negative_placement(self):
        assert calculate_cp("REGIONAL", -1, 100) == 0

    def test_edge_case_zero_competitors(self):
        assert calculate_cp("REGIONAL", 1, 0) == 0

    def test_edge_case_negative_competitors(self):
        assert calculate_cp("REGIONAL", 1, -1) == 0

    def test_placement_beyond_any_bracket(self):
        assert calculate_cp("REGIONAL", 10_000, 10_000) == 0

    def test_picks_bracket_with_largest_kicker(self):
        """When multiple bracket placement ranges match, the one with the largest
        kicker that is still <= num_competitors should be chosen."""
        result = calculate_cp("REGIONAL", 5, 100)
        assert result == 280, f"Expected 280, got {result}"

    def test_kicker_boundary_exact(self):
        """Exactly at kicker threshold should match."""
        assert calculate_cp("REGIONAL", 9, 33) == 200
        assert calculate_cp("REGIONAL", 9, 32) == 0

    def test_unknown_type_falls_back_to_regional(self):
        result = calculate_cp("SPECIAL", 1, 100)
        assert result == 350

    def test_empty_type_falls_back_to_regional(self):
        result = calculate_cp("", 1, 100)
        assert result == 350

    def test_stripped_type(self):
        result = calculate_cp("  IC  ", 1, 500)
        assert result == 500
