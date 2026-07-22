"""Very small test stubs for CP calculation and parsers.

You can run these with:  python -m pytest  (if pytest is installed)
or simply run:  python tests_cp_parsing.py
"""

from cp_calculator import calculate_cp
from parsers import parse_format_a, parse_format_b


def test_cp_basic():
    assert calculate_cp("REGIONAL", 1, 100) == 350
    assert calculate_cp("REGIONAL", 2, 10) == 325
    assert calculate_cp("IC", 1, 500) == 500
    assert calculate_cp("IC", 70, 300) == 140


def test_parse_format_a():
    text = "1. Tord Reklev [NO]\n2. Liam Halliburton [US]"
    entries = parse_format_a(text)
    assert len(entries) == 2
    assert entries[0].placement == 1
    assert entries[0].region_code == "NO"


def test_parse_format_b():
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
    assert len(entries) >= 2
    assert entries[0].placement == 1
    assert entries[0].region_code == "CL"


if __name__ == "__main__":
    test_cp_basic()
    test_parse_format_a()
    test_parse_format_b()
    print("Basic tests passed.")



