from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def sample_address(**overrides):
    data = {
        "address_line1": "  221B   Baker Street ",
        "address_line2": " ",
        "city": " London ",
        "state": " ",
        "postal_code": "NW1 6XE",
        "country_code": "gb",
    }
    data.update(overrides)
    return data


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_normalizes_fields():
    response = client.post("/v1/validate", json=sample_address())
    assert response.status_code == 200
    body = response.json()
    assert body["normalized_address"]["address_line1"] == "221B Baker Street"
    assert body["normalized_address"]["country_code"] == "GB"
    assert body["normalized_address"]["address_line2"] is None
    assert body["verification_level"] == "format_only"


def test_invalid_indian_postal_code():
    response = client.post(
        "/v1/validate",
        json=sample_address(country_code="IN", postal_code="123"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert any(issue["code"] == "postal_code_format_invalid" for issue in body["issues"])


def test_batch_validation():
    response = client.post(
        "/v1/batch-validate",
        json={"addresses": [sample_address(), sample_address(country_code="IN", postal_code="12")]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 2


def test_rejects_unknown_fields():
    response = client.post("/v1/validate", json=sample_address(extra_field="no"))
    assert response.status_code == 422


def test_postal_code_spacing_is_normalized():
    body = client.post(
        "/v1/validate",
        json=sample_address(
            country_code="IN",
            postal_code="560 001",
            city="Bengaluru",
            state="Karnataka",
        ),
    ).json()
    assert body["is_valid"] is True
    assert body["normalized_address"]["postal_code"] == "560001"
    body = client.post("/v1/validate", json=sample_address(postal_code="nw16xe")).json()
    assert body["is_valid"] is True
    assert body["normalized_address"]["postal_code"] == "NW1 6XE"


def test_missing_postal_code_invalid_where_required():
    body = client.post("/v1/validate", json=sample_address(country_code="IN", postal_code=None)).json()
    assert body["is_valid"] is False
    assert any(i["code"] == "postal_code_missing" for i in body["issues"])


def test_hong_kong_country_code_recognized():
    body = client.post("/v1/validate", json=sample_address(country_code="HK", postal_code=None)).json()
    assert body["checks"]["country_code_recognized"] is True
    assert body["is_valid"] is True


def test_non_ascii_digits_rejected():
    body = client.post("/v1/validate", json=sample_address(country_code="DE", postal_code="١٢٣٤٥")).json()
    assert body["is_valid"] is False


def test_marketplace_proxy_secret_auth(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "API_KEY", "")
    monkeypatch.setattr(m, "PROXY_SECRET", "s3cret")
    assert client.post("/v1/validate", json=sample_address()).status_code == 401
    ok = client.post("/v1/validate", json=sample_address(), headers={"X-RapidAPI-Proxy-Secret": "s3cret"})
    assert ok.status_code == 200


def test_india_pin_state_and_city_match():
    """Known good Bengaluru address should pass PIN↔location checks."""
    body = client.post(
        "/v1/validate",
        json={
            "address_line1": "12 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560001",
            "country_code": "IN",
        },
    ).json()
    assert body["is_valid"] is True
    assert body["verification_level"] == "india_pin_matched"
    assert body["checks"].get("india_pin_known") is True
    assert body["checks"].get("india_state_match") is True
    assert body["checks"].get("india_city_district_match") is True
    assert body["normalized_address"]["india_post"]["state"] == "KARNATAKA"
    assert "BENGALURU URBAN" in body["normalized_address"]["india_post"]["districts"]


def test_india_pin_city_mismatch_flags():
    """Wrong city for a PIN should be invalid (fraud signal)."""
    body = client.post(
        "/v1/validate",
        json={
            "address_line1": "Fake Street",
            "city": "Mumbai",
            "state": "Maharashtra",
            "postal_code": "560001",
            "country_code": "IN",
        },
    ).json()
    assert body["is_valid"] is False
    assert any(i["code"] == "india_city_district_mismatch" for i in body["issues"])
    assert any(i["code"] == "india_state_mismatch" for i in body["issues"])


def test_india_pin_unknown():
    """Well-formed but non-existent PIN is flagged."""
    body = client.post(
        "/v1/validate",
        json={
            "address_line1": "Somewhere",
            "city": "Nowhere",
            "state": "Karnataka",
            "postal_code": "999999",
            "country_code": "IN",
        },
    ).json()
    assert body["is_valid"] is False
    assert any(i["code"] == "india_pin_unknown" for i in body["issues"])


def test_india_bangalore_alias():
    """Bangalore (old spelling) should match Bengaluru Urban district."""
    body = client.post(
        "/v1/validate",
        json={
            "address_line1": "1 Main Road",
            "city": "Bangalore",
            "state": "KA",
            "postal_code": "560001",
            "country_code": "IN",
        },
    ).json()
    assert body["is_valid"] is True
    assert body["checks"].get("india_city_district_match") is True
    assert body["checks"].get("india_state_match") is True
