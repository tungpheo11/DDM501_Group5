"""
Integration tests for API endpoints.

Run tests:
    pytest tests/integration/test_api.py -v
"""

import pytest


class TestHealthEndpoint:
    """Integration tests for /health endpoint."""

    # =========================================================================
    # Provided Tests
    # =========================================================================

    def test_health_returns_200(self, test_client):
        """Test that health endpoint returns 200 status code."""
        response = test_client.get("/health")
        assert response.status_code == 200

    def test_health_response_has_status_field(self, test_client):
        """Test that health response has status field."""
        response = test_client.get("/health")
        data = response.json()
        assert "status" in data

    # =========================================================================
    # TODO 1: Implement Additional Health Tests
    # =========================================================================

    def test_health_response_has_model_loaded_field(self, test_client):
        """
        Test that health response has model_loaded field.
        """
        response = test_client.get("/health")
        data = response.json()
        assert "model_loaded" in data

    def test_health_model_loaded_is_boolean(self, test_client):
        """
        Test that model_loaded is a boolean value.
        """
        response = test_client.get("/health")
        data = response.json()
        assert isinstance(data["model_loaded"], bool)


class TestRootEndpoint:
    """Integration tests for / endpoint."""

    def test_root_returns_200(self, test_client):
        """Test that root endpoint returns 200 status code."""
        response = test_client.get("/")
        assert response.status_code == 200

    # =========================================================================
    # TODO 2: Implement Root Endpoint Tests
    # =========================================================================

    def test_root_contains_api_info(self, test_client):
        """
        Test that root response contains API information.
        """
        response = test_client.get("/")
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "docs" in data


class TestPredictEndpoint:
    """Integration tests for /predict endpoint."""

    # =========================================================================
    # Provided Tests
    # =========================================================================

    def test_predict_valid_request_returns_200(self, test_client, sample_prediction_request):
        """Test that valid prediction request returns 200."""
        response = test_client.post("/predict", json=sample_prediction_request)
        assert response.status_code == 200

    # =========================================================================
    # TODO 3: Implement Response Structure Tests
    # =========================================================================

    def test_predict_response_has_predicted_rating(self, test_client, sample_prediction_request):
        """
        Test that response contains predicted_rating field.
        """
        response = test_client.post("/predict", json=sample_prediction_request)
        data = response.json()
        assert "predicted_rating" in data

    def test_predict_response_has_user_id(self, test_client, sample_prediction_request):
        """
        Test that response contains user_id field.
        """
        response = test_client.post("/predict", json=sample_prediction_request)
        data = response.json()
        assert "user_id" in data

    def test_predict_response_has_movie_id(self, test_client, sample_prediction_request):
        """
        Test that response contains movie_id field.
        """
        response = test_client.post("/predict", json=sample_prediction_request)
        data = response.json()
        assert "movie_id" in data

    def test_predict_response_rating_in_valid_range(self, test_client, sample_prediction_request):
        """
        Test that predicted_rating is between 1.0 and 5.0.
        """
        response = test_client.post("/predict", json=sample_prediction_request)
        data = response.json()
        assert 1.0 <= data["predicted_rating"] <= 5.0

    # =========================================================================
    # TODO 4: Implement Validation Error Tests
    # =========================================================================

    def test_predict_missing_user_id_returns_422(self, test_client):
        """
        Test that missing user_id returns 422 Unprocessable Entity.
        """
        response = test_client.post("/predict", json={"movie_id": "242"})
        assert response.status_code == 422

    def test_predict_missing_movie_id_returns_422(self, test_client):
        """
        Test that missing movie_id returns 422.
        """
        response = test_client.post("/predict", json={"user_id": "196"})
        assert response.status_code == 422

    def test_predict_empty_body_returns_422(self, test_client):
        """
        Test that empty request body returns 422.
        """
        response = test_client.post("/predict", json={})
        assert response.status_code == 422

    def test_predict_invalid_json_returns_422(self, test_client):
        """
        Test that invalid JSON returns 422.
        """
        response = test_client.post(
            "/predict",
            content="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    # =========================================================================
    # TODO 5: Implement Multiple Request Tests
    # =========================================================================

    def test_predict_multiple_valid_requests(self, test_client, known_user_movie_pairs):
        """
        Test multiple prediction requests all succeed.
        """
        for pair in known_user_movie_pairs:
            response = test_client.post(
                "/predict",
                json={"user_id": pair["user_id"], "movie_id": pair["movie_id"]},
            )
            assert response.status_code == 200


class TestBatchPredictEndpoint:
    """Integration tests for /predict/batch endpoint."""

    # =========================================================================
    # TODO 6: Implement Batch Prediction Tests
    # =========================================================================

    def test_batch_predict_returns_200(self, test_client, sample_batch_request):
        """
        Test that batch prediction returns 200.
        """
        response = test_client.post("/predict/batch", json=sample_batch_request)
        assert response.status_code == 200

    def test_batch_predict_returns_correct_count(self, test_client, sample_batch_request):
        """
        Test that batch prediction returns correct number of results.
        """
        response = test_client.post("/predict/batch", json=sample_batch_request)
        data = response.json()
        expected_count = len(sample_batch_request["predictions"])
        assert data["total_count"] == expected_count
        assert len(data["predictions"]) == expected_count

    def test_batch_predict_all_ratings_in_range(self, test_client, sample_batch_request):
        """
        Test that all batch predictions are in valid range.
        """
        response = test_client.post("/predict/batch", json=sample_batch_request)
        data = response.json()
        for prediction in data["predictions"]:
            assert 1.0 <= prediction["predicted_rating"] <= 5.0


class TestErrorHandling:
    """Tests for API error handling."""

    # =========================================================================
    # TODO 7: Implement Error Handling Tests
    # =========================================================================

    def test_404_for_unknown_endpoint(self, test_client):
        """
        Test that unknown endpoint returns 404.
        """
        response = test_client.get("/unknown")
        assert response.status_code == 404

    def test_method_not_allowed_get_predict(self, test_client):
        """
        Test that GET /predict returns 405 Method Not Allowed.
        """
        response = test_client.get("/predict")
        assert response.status_code == 405

    def test_method_not_allowed_post_health(self, test_client):
        """
        Test that POST /health returns 405.
        """
        response = test_client.post("/health")
        assert response.status_code == 405


class TestModelInfoEndpoint:
    """Tests for /model/info endpoint."""

    def test_model_info_returns_200(self, test_client):
        """Test that model info endpoint returns 200."""
        response = test_client.get("/model/info")
        assert response.status_code == 200

    # =========================================================================
    # TODO 8: Implement Model Info Tests
    # =========================================================================

    def test_model_info_has_version(self, test_client):
        """
        Test that model info has version field.
        """
        response = test_client.get("/model/info")
        data = response.json()
        assert "model_version" in data

    def test_model_info_has_is_loaded(self, test_client):
        """
        Test that model info has is_loaded field.
        """
        response = test_client.get("/model/info")
        data = response.json()
        assert "is_loaded" in data


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
