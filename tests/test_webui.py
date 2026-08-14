"""Web UI smoke tests: example loading, payload construction and
result formatting (HTTP mocked with monkeypatch)."""

import httpx

from services.webui import app as webui


def form_values() -> list:
    """One valid value per field, in ALL_FIELDS order."""
    values = []
    for field in webui.ALL_FIELDS:
        if field in webui.CHOICES:
            values.append(webui.CHOICES[field][0])
        elif field == "SeniorCitizen":
            values.append(0)
        else:
            values.append(1.0)
    return values


def fake_response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status, json=body, request=httpx.Request("POST", "http://test/predict")
    )


def test_load_example_returns_the_19_fields():
    example = webui.load_example()
    assert set(example) == set(webui.ALL_FIELDS)
    assert len(example) == 19
    for field, choices in webui.CHOICES.items():
        assert example[field] in choices
    assert example["SeniorCitizen"] in (0, 1)
    assert 0 <= example["tenure"] <= 72
    assert isinstance(example["MonthlyCharges"], float)
    assert isinstance(example["TotalCharges"], float)


def test_build_payload_maps_values_in_order():
    values = form_values()
    assert webui.build_payload(values) == dict(zip(webui.ALL_FIELDS, values))


def test_predict_success_with_offer(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)
    monkeypatch.setattr(
        webui.httpx,
        "post",
        lambda *a, **k: fake_response(
            200, {"churn_probability": 0.7, "recommended_offer": "discount"}
        ),
    )
    proba, verdict, offer = webui.predict(*form_values())
    assert proba == 0.7
    assert "Churn likely" in verdict
    assert offer == "discount"


def test_predict_below_threshold_verdict_unlikely(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)
    monkeypatch.setattr(
        webui.httpx,
        "post",
        lambda *a, **k: fake_response(
            200, {"churn_probability": 0.3, "recommended_offer": "no_offer"}
        ),
    )
    proba, verdict, offer = webui.predict(*form_values())
    assert proba == 0.3
    assert "Churn unlikely" in verdict
    assert offer == webui.NO_OFFER_MESSAGE


def test_predict_service_unreachable(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)

    def boom(*a, **k):
        raise httpx.RequestError("connection refused")

    monkeypatch.setattr(webui.httpx, "post", boom)
    proba, verdict, offer = webui.predict(*form_values())
    assert proba == 0.0
    assert "Could not reach" in verdict
    assert offer == ""


def test_predict_timeout(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)

    def boom(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(webui.httpx, "post", boom)
    _, verdict, _ = webui.predict(*form_values())
    assert "timed out" in verdict


def test_predict_422(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)
    monkeypatch.setattr(
        webui.httpx, "post", lambda *a, **k: fake_response(422, {"detail": "x"})
    )
    _, verdict, _ = webui.predict(*form_values())
    assert "422" in verdict


def test_predict_unexpected_status(monkeypatch):
    monkeypatch.setattr(webui, "get_threshold", lambda: 0.5)
    monkeypatch.setattr(
        webui.httpx, "post", lambda *a, **k: fake_response(500, {})
    )
    _, verdict, _ = webui.predict(*form_values())
    assert "500" in verdict


def test_get_threshold_ok(monkeypatch):
    monkeypatch.setattr(
        webui.httpx,
        "get",
        lambda *a, **k: fake_response(200, {"status": "ok", "threshold": 0.35}),
    )
    assert webui.get_threshold() == 0.35


def test_get_threshold_fallback_when_unreachable(monkeypatch):
    def boom(*a, **k):
        raise httpx.RequestError("connection refused")

    monkeypatch.setattr(webui.httpx, "get", boom)
    assert webui.get_threshold() == webui.DEFAULT_THRESHOLD


def test_ui_builds_with_19_inputs():
    demo = webui.build_ui()
    assert isinstance(demo, webui.gr.Blocks)
