"""
Unit tests for utility/config values.

Run tests:
    pytest tests/unit/test_utils.py -v
"""

import pytest

from app.config import (
    API_DESCRIPTION,
    API_TITLE,
    API_VERSION,
    MAX_RATING,
    MIN_RATING,
    MODEL_VERSION,
)


class TestConfigValues:
    """Tests for application configuration constants."""

    def test_min_rating_is_one(self):
        """Rating floor must be 1.0 as per MovieLens spec."""
        assert MIN_RATING == 1.0

    def test_max_rating_is_five(self):
        """Rating ceiling must be 5.0 as per MovieLens spec."""
        assert MAX_RATING == 5.0

    def test_rating_range_is_valid(self):
        """Min rating must be strictly less than max rating."""
        assert MIN_RATING < MAX_RATING

    def test_api_title_is_string(self):
        """API title must be a non-empty string."""
        assert isinstance(API_TITLE, str)
        assert len(API_TITLE) > 0

    def test_api_version_format(self):
        """API version should follow semver pattern x.y.z."""
        parts = API_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_model_version_format(self):
        """Model version should follow semver pattern x.y.z."""
        parts = MODEL_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_api_description_is_string(self):
        """API description must be a non-empty string."""
        assert isinstance(API_DESCRIPTION, str)
        assert len(API_DESCRIPTION) > 0


class TestRatingConstraints:
    """Tests validating rating boundary logic used throughout the app."""

    def test_boundary_values_are_valid(self):
        """Exact boundary values (1.0 and 5.0) must be accepted."""
        assert MIN_RATING <= 1.0 <= MAX_RATING
        assert MIN_RATING <= 5.0 <= MAX_RATING

    def test_below_min_is_out_of_range(self):
        """Values below MIN_RATING must be out of range."""
        assert 0.9 < MIN_RATING

    def test_above_max_is_out_of_range(self):
        """Values above MAX_RATING must be out of range."""
        assert 5.1 > MAX_RATING

    def test_midpoint_is_valid(self):
        """Midpoint of range must be valid."""
        midpoint = (MIN_RATING + MAX_RATING) / 2
        assert MIN_RATING <= midpoint <= MAX_RATING


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
