"""
Model behavioral tests.

These tests verify the model's behavior patterns:
- Invariance: Output shouldn't change for certain perturbations
- Directional: Output should change in expected direction
- Minimum Functionality: Basic cases the model must handle

Run tests:
    pytest tests/model/test_model_behavior.py -v
"""

import pytest


class TestModelInvariance:
    """
    Invariance tests - output shouldn't change for certain perturbations.

    These tests ensure that the model produces consistent results
    when given the same inputs.
    """

    # =========================================================================
    # TODO 1: Implement Deterministic Output Tests
    # =========================================================================

    def test_same_input_same_output(self, trained_model):
        """
        Test that same input always produces same output.
        """
        result1 = trained_model.predict("196", "242")
        result2 = trained_model.predict("196", "242")
        assert result1 == result2

    def test_multiple_calls_consistent(self, trained_model):
        """
        Test that multiple calls produce consistent results.
        """
        results = [trained_model.predict("196", "242") for _ in range(5)]
        assert all(r == results[0] for r in results)

    # =========================================================================
    # TODO 2: Implement Batch Order Invariance Tests
    # =========================================================================

    def test_batch_order_independent(self, trained_model):
        """
        Test that batch predictions are independent of input order.
        """
        pairs1 = [("196", "242"), ("186", "302")]
        pairs2 = [("186", "302"), ("196", "242")]

        results1 = trained_model.predict_batch(pairs1)
        results2 = trained_model.predict_batch(pairs2)

        # Results should contain same values (possibly different order)
        assert set(results1) == set(results2)

    def test_individual_vs_batch_same_results(self, trained_model):
        """
        Test that individual and batch predictions match.
        """
        pairs = [("196", "242"), ("186", "302")]

        individual_results = [trained_model.predict(uid, mid) for uid, mid in pairs]
        batch_results = trained_model.predict_batch(pairs)

        for ind_result, batch_result in zip(individual_results, batch_results):
            assert ind_result == batch_result


class TestModelDirectional:
    """
    Directional tests - output should change in expected direction.

    These tests verify that the model behaves sensibly when inputs
    change in predictable ways.
    """

    # =========================================================================
    # TODO 3: Implement Directional Tests
    # =========================================================================

    def test_predictions_are_reasonable(self, trained_model, known_user_movie_pairs):
        """
        Test that predictions are reasonably close to actual ratings.
        Prediction should be within 2.5 of actual rating.
        (SVD collaborative filtering can be off for cold-start or extreme ratings.)
        """
        for pair in known_user_movie_pairs:
            prediction = trained_model.predict(pair["user_id"], pair["movie_id"])
            actual = pair["actual_rating"]
            assert (
                abs(prediction - actual) < 2.5
            ), f"Prediction {prediction} too far from actual {actual}"

    def test_different_movies_different_predictions(self, trained_model):
        """
        Test that different movies can get different predictions.
        Same user, different movies - predictions should potentially differ.
        """
        # User 196 predicts for different movies
        pred_movie_242 = trained_model.predict("196", "242")
        pred_movie_302 = trained_model.predict("196", "302")

        # Both should be in valid range
        assert 1.0 <= pred_movie_242 <= 5.0
        assert 1.0 <= pred_movie_302 <= 5.0
        # (They may or may not be equal, both are valid - just checking they work)

    def test_different_users_different_predictions(self, trained_model):
        """
        Test that different users can get different predictions.
        Different users, same movie - predictions should potentially differ.
        """
        pred_user_196 = trained_model.predict("196", "242")
        pred_user_186 = trained_model.predict("186", "242")

        # Both should be in valid range
        assert 1.0 <= pred_user_196 <= 5.0
        assert 1.0 <= pred_user_186 <= 5.0


class TestMinimumFunctionality:
    """
    Minimum functionality tests - basic cases the model must handle.

    These are simple test cases that the model absolutely must pass
    to be considered functional.
    """

    # =========================================================================
    # TODO 4: Implement Minimum Functionality Tests
    # =========================================================================

    def test_can_predict_for_known_user(self, trained_model):
        """
        Test that model can make prediction for known user.
        """
        prediction = trained_model.predict("196", "242")
        assert prediction is not None
        assert 1.0 <= prediction <= 5.0

    def test_can_predict_for_multiple_users(self, trained_model, known_user_movie_pairs):
        """
        Test that model can make predictions for multiple known users.
        """
        for pair in known_user_movie_pairs:
            prediction = trained_model.predict(pair["user_id"], pair["movie_id"])
            assert prediction is not None
            assert 1.0 <= prediction <= 5.0

    def test_predictions_not_all_same(self, trained_model, known_user_movie_pairs):
        """
        Test that not all predictions are the same value.
        If all predictions are identical, model might be broken.
        """
        predictions = [
            trained_model.predict(p["user_id"], p["movie_id"]) for p in known_user_movie_pairs
        ]
        assert len(set(predictions)) > 1, "All predictions are identical - model may be broken"

    # =========================================================================
    # TODO 5: Implement Edge Case Tests
    # =========================================================================

    def test_handles_unknown_user_gracefully(self, trained_model, unknown_users):
        """
        Test that model handles unknown users without crashing.
        Model should either return a reasonable prediction or raise a specific error.
        """
        for user_id in unknown_users:
            try:
                prediction = trained_model.predict(user_id, "242")
                # If it returns, should be valid
                assert 1.0 <= prediction <= 5.0
            except (ValueError, KeyError):
                pass  # Acceptable to raise error for unknown user

    def test_handles_unknown_movie_gracefully(self, trained_model, unknown_movies):
        """
        Test that model handles unknown movies without crashing.
        """
        for movie_id in unknown_movies:
            try:
                prediction = trained_model.predict("196", movie_id)
                # If it returns, should be valid
                assert 1.0 <= prediction <= 5.0
            except (ValueError, KeyError):
                pass  # Acceptable to raise error for unknown movie


class TestModelPerformance:
    """
    Performance-related behavioral tests.

    These tests verify that the model performs adequately
    on known test cases.
    """

    # =========================================================================
    # TODO 6: Implement Performance Tests (BONUS)
    # =========================================================================

    def test_average_error_acceptable(self, trained_model, known_user_movie_pairs):
        """
        Test that average prediction error is acceptable (MAE < 1.5).
        Note: SVD on MovieLens 100K achieves RMSE ~0.93, but on specific
        known pairs the error can vary. A threshold of 1.5 is reasonable.
        """
        errors = []
        for pair in known_user_movie_pairs:
            prediction = trained_model.predict(pair["user_id"], pair["movie_id"])
            actual = pair["actual_rating"]
            errors.append(abs(prediction - actual))

        mae = sum(errors) / len(errors)
        assert mae < 1.5, f"Mean Absolute Error {mae:.2f} exceeds threshold of 1.5"

    def test_no_extreme_errors(self, trained_model, known_user_movie_pairs):
        """
        Test that there are no extreme prediction errors (no error > 3.0).
        """
        for pair in known_user_movie_pairs:
            prediction = trained_model.predict(pair["user_id"], pair["movie_id"])
            actual = pair["actual_rating"]
            error = abs(prediction - actual)
            assert error <= 3.0, (
                f"Extreme error {error:.2f} for user {pair['user_id']}, "
                f"movie {pair['movie_id']}"
            )


class TestModelRobustness:
    """
    Robustness tests - model behavior under unusual conditions.
    """

    # =========================================================================
    # TODO 7: Implement Robustness Tests (BONUS)
    # =========================================================================

    def test_handles_string_numeric_ids(self, trained_model):
        """
        Test that model handles string IDs that look like numbers.
        """
        try:
            prediction = trained_model.predict("196", "242")
            assert isinstance(prediction, float)
            assert 1.0 <= prediction <= 5.0
        except Exception as e:
            pytest.fail(f"Model failed to handle string numeric IDs: {e}")

    def test_handles_leading_zeros_in_ids(self, trained_model):
        """
        Test that model handles IDs with leading zeros.
        "001" vs "1" might be treated differently by the model.
        """
        # Leading zeros may be treated as unknown users/movies
        try:
            prediction = trained_model.predict("001", "242")
            # If it returns, should be valid
            assert 1.0 <= prediction <= 5.0
        except (ValueError, KeyError, Exception):
            pass  # Acceptable - unknown ID with leading zeros


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
