from app.awr.utils import _safe_float


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_integer(self):
        assert _safe_float(42) == 42.0

    def test_string_number(self):
        assert _safe_float('123.45') == 123.45

    def test_string_with_comma(self):
        # _safe_float strips commas, so '1,234.56' -> '1234.56'
        assert _safe_float('1,234.56') == 1234.56

    def test_string_with_percent(self):
        # _safe_float strips %, so '95.5%' -> '95.5'
        assert _safe_float('95.5%') == 95.5

    def test_string_with_spaces(self):
        # _safe_float strips whitespace
        assert _safe_float(' 42.0 ') == 42.0

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_none_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0

    def test_empty_string(self):
        # Empty string after stripping -> '' -> float('') fails -> default
        assert _safe_float('') == 0.0

    def test_non_numeric_string(self):
        assert _safe_float('abc') == 0.0

    def test_mixed_invalid(self):
        assert _safe_float('N/A') == 0.0

    def test_zero(self):
        assert _safe_float(0) == 0.0

    def test_negative(self):
        assert _safe_float(-5.5) == -5.5

    def test_string_negative(self):
        assert _safe_float('-10.5') == -10.5
