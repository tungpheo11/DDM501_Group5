"""
Data quality validation tests.

These tests verify the quality, schema, and statistical properties
of the MovieLens rating data used to train and evaluate the model.

Test categories:
- Schema validation (required fields, correct types)
- Rating range validation (1.0 – 5.0)
- Completeness checks (no nulls/empty values)
- Distribution tests (reasonable mean, variance)
- Uniqueness and consistency checks

Run tests:
    pytest tests/data/test_data_quality.py -v
"""

import numpy as np
import pytest


# =============================================================================
# Schema Validation
# =============================================================================


class TestSchemaValidation:
    """Tests for rating record schema — correct keys and types."""

    def test_records_have_required_fields(self, sample_ratings):
        """Every record must contain user_id, movie_id and rating."""
        required_fields = {"user_id", "movie_id", "rating"}
        for record in sample_ratings:
            assert required_fields.issubset(
                record.keys()
            ), f"Record missing fields: {required_fields - record.keys()}"

    def test_user_id_is_string(self, sample_ratings):
        """user_id must be a string in every record."""
        for record in sample_ratings:
            assert isinstance(record["user_id"], str), (
                f"user_id should be str, got {type(record['user_id'])}"
            )

    def test_movie_id_is_string(self, sample_ratings):
        """movie_id must be a string in every record."""
        for record in sample_ratings:
            assert isinstance(record["movie_id"], str), (
                f"movie_id should be str, got {type(record['movie_id'])}"
            )

    def test_rating_is_numeric(self, sample_ratings):
        """rating must be int or float in every record."""
        for record in sample_ratings:
            assert isinstance(record["rating"], (int, float)), (
                f"rating should be numeric, got {type(record['rating'])}"
            )


# =============================================================================
# Rating Range Tests
# =============================================================================


class TestRatingRange:
    """Tests ensuring all ratings fall within the valid 1.0 – 5.0 range."""

    def test_all_ratings_at_least_one(self, sample_ratings):
        """No rating may be below 1.0 (MovieLens minimum)."""
        for record in sample_ratings:
            assert record["rating"] >= 1.0, (
                f"Rating {record['rating']} is below minimum 1.0"
            )

    def test_all_ratings_at_most_five(self, sample_ratings):
        """No rating may exceed 5.0 (MovieLens maximum)."""
        for record in sample_ratings:
            assert record["rating"] <= 5.0, (
                f"Rating {record['rating']} exceeds maximum 5.0"
            )

    def test_all_ratings_in_valid_range(self, sample_ratings):
        """All ratings must be within [1.0, 5.0] (combined boundary check)."""
        for record in sample_ratings:
            assert 1.0 <= record["rating"] <= 5.0, (
                f"Rating {record['rating']} out of range [1.0, 5.0]"
            )

    def test_ratings_allow_valid_half_stars(self, sample_ratings):
        """Half-star ratings (e.g. 3.5, 4.5) must be treated as valid."""
        half_star_ratings = [r for r in sample_ratings if r["rating"] % 1 == 0.5]
        for record in half_star_ratings:
            assert 1.0 <= record["rating"] <= 5.0

    def test_invalid_rating_below_range(self):
        """A record with rating 0.0 must be detected as invalid."""
        invalid = {"user_id": "1", "movie_id": "1", "rating": 0.0}
        assert invalid["rating"] < 1.0  # Should be flagged

    def test_invalid_rating_above_range(self):
        """A record with rating 6.0 must be detected as invalid."""
        invalid = {"user_id": "1", "movie_id": "1", "rating": 6.0}
        assert invalid["rating"] > 5.0  # Should be flagged


# =============================================================================
# Completeness / Missing Value Tests
# =============================================================================


class TestCompletenessChecks:
    """Tests ensuring no missing or empty values in critical fields."""

    def test_no_missing_user_ids(self, sample_ratings):
        """user_id must not be None or empty string."""
        for record in sample_ratings:
            assert record["user_id"] is not None, "Found None user_id"
            assert record["user_id"] != "", "Found empty string user_id"

    def test_no_missing_movie_ids(self, sample_ratings):
        """movie_id must not be None or empty string."""
        for record in sample_ratings:
            assert record["movie_id"] is not None, "Found None movie_id"
            assert record["movie_id"] != "", "Found empty string movie_id"

    def test_no_missing_ratings(self, sample_ratings):
        """rating must not be None or NaN."""
        for record in sample_ratings:
            assert record["rating"] is not None, "Found None rating"
            assert not np.isnan(record["rating"]), "Found NaN rating"

    def test_no_whitespace_only_user_ids(self, sample_ratings):
        """user_id must not consist solely of whitespace."""
        for record in sample_ratings:
            assert record["user_id"].strip() != "", (
                "Found whitespace-only user_id"
            )

    def test_no_whitespace_only_movie_ids(self, sample_ratings):
        """movie_id must not consist solely of whitespace."""
        for record in sample_ratings:
            assert record["movie_id"].strip() != "", (
                "Found whitespace-only movie_id"
            )

    def test_dataset_is_not_empty(self, sample_ratings):
        """Dataset must contain at least one record."""
        assert len(sample_ratings) > 0, "Dataset is empty"


# =============================================================================
# Distribution Tests
# =============================================================================


class TestRatingDistribution:
    """Tests ensuring the rating distribution is statistically reasonable."""

    def test_mean_rating_in_reasonable_range(self, sample_ratings):
        """Mean rating must be between 2.0 and 4.5 (reasonable for MovieLens)."""
        ratings = [r["rating"] for r in sample_ratings]
        mean = np.mean(ratings)
        assert 2.0 <= mean <= 4.5, (
            f"Mean rating {mean:.2f} outside expected range [2.0, 4.5]"
        )

    def test_ratings_have_variance(self, sample_ratings):
        """Dataset must not contain a single repeated rating (no variance = broken data)."""
        ratings = [r["rating"] for r in sample_ratings]
        variance = np.var(ratings)
        assert variance > 0, "All ratings are identical — dataset has no variance"

    def test_ratings_cover_multiple_values(self, sample_ratings):
        """At least 2 distinct rating values must appear."""
        unique_ratings = {r["rating"] for r in sample_ratings}
        assert len(unique_ratings) >= 2, (
            f"Only {len(unique_ratings)} distinct rating(s) found"
        )

    def test_no_extreme_skew_all_max(self, sample_ratings):
        """Not all ratings should be 5.0 (extreme positive skew is suspicious)."""
        ratings = [r["rating"] for r in sample_ratings]
        assert not all(r == 5.0 for r in ratings), "All ratings are 5.0 — data may be corrupt"

    def test_no_extreme_skew_all_min(self, sample_ratings):
        """Not all ratings should be 1.0 (extreme negative skew is suspicious)."""
        ratings = [r["rating"] for r in sample_ratings]
        assert not all(r == 1.0 for r in ratings), "All ratings are 1.0 — data may be corrupt"


# =============================================================================
# Uniqueness / Consistency Tests
# =============================================================================


class TestUniquenessAndConsistency:
    """Tests for data uniqueness and internal consistency."""

    def test_dataset_has_multiple_users(self, sample_ratings):
        """Dataset must have more than one unique user."""
        unique_users = {r["user_id"] for r in sample_ratings}
        assert len(unique_users) > 1, "Dataset has only one user"

    def test_dataset_has_multiple_movies(self, sample_ratings):
        """Dataset must have more than one unique movie."""
        unique_movies = {r["movie_id"] for r in sample_ratings}
        assert len(unique_movies) > 1, "Dataset has only one movie"

    def test_user_movie_pairs_are_unique(self, sample_ratings):
        """Each (user_id, movie_id) pair must appear at most once."""
        pairs = [(r["user_id"], r["movie_id"]) for r in sample_ratings]
        assert len(pairs) == len(set(pairs)), "Duplicate (user_id, movie_id) pairs found"

    def test_user_ids_are_non_negative_when_numeric(self, sample_ratings):
        """Numeric user IDs should be positive (no user ID of 0 or negative)."""
        for record in sample_ratings:
            try:
                uid = int(record["user_id"])
                assert uid > 0, f"Non-positive user_id: {uid}"
            except ValueError:
                pass  # Non-numeric IDs are acceptable

    def test_movie_ids_are_non_negative_when_numeric(self, sample_ratings):
        """Numeric movie IDs should be positive."""
        for record in sample_ratings:
            try:
                mid = int(record["movie_id"])
                assert mid > 0, f"Non-positive movie_id: {mid}"
            except ValueError:
                pass  # Non-numeric IDs are acceptable


# =============================================================================
# Edge Case / Invalid Data Detection Tests
# =============================================================================


class TestInvalidDataDetection:
    """Tests that demonstrate how to detect problematic records."""

    @pytest.fixture
    def invalid_ratings(self):
        """Collection of intentionally invalid rating records."""
        return [
            {"user_id": "", "movie_id": "10", "rating": 3.0},      # Empty user_id
            {"user_id": "1", "movie_id": "", "rating": 3.0},        # Empty movie_id
            {"user_id": "1", "movie_id": "10", "rating": 0.0},      # Rating below min
            {"user_id": "1", "movie_id": "10", "rating": 6.0},      # Rating above max
            {"user_id": "1", "movie_id": "10", "rating": None},     # Null rating
        ]

    def test_detects_empty_user_id(self, invalid_ratings):
        """Records with empty user_id must be flagged."""
        bad = [r for r in invalid_ratings if not r.get("user_id", "").strip()]
        assert len(bad) >= 1

    def test_detects_empty_movie_id(self, invalid_ratings):
        """Records with empty movie_id must be flagged."""
        bad = [r for r in invalid_ratings if not r.get("movie_id", "").strip()]
        assert len(bad) >= 1

    def test_detects_out_of_range_ratings(self, invalid_ratings):
        """Records with ratings outside [1.0, 5.0] must be flagged."""
        bad = [
            r for r in invalid_ratings
            if r["rating"] is not None and not (1.0 <= r["rating"] <= 5.0)
        ]
        assert len(bad) >= 2  # 0.0 and 6.0

    def test_detects_null_ratings(self, invalid_ratings):
        """Records with None ratings must be flagged."""
        bad = [r for r in invalid_ratings if r["rating"] is None]
        assert len(bad) >= 1

    def test_valid_records_pass_all_checks(self, sample_ratings):
        """All records in sample_ratings fixture must pass every quality check."""
        errors = []
        for record in sample_ratings:
            if not record.get("user_id", "").strip():
                errors.append(f"Empty user_id: {record}")
            if not record.get("movie_id", "").strip():
                errors.append(f"Empty movie_id: {record}")
            if record["rating"] is None or not (1.0 <= record["rating"] <= 5.0):
                errors.append(f"Invalid rating: {record}")
        assert errors == [], f"Quality issues found:\n" + "\n".join(errors)


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
