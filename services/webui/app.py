"""Gradio demo UI for the churn prediction platform (portfolio demo).

Thin client of the inference service: it sends a raw customer profile
(19 fields, as in data/churn.csv) to POST {INFERENCE_URL}/predict and
displays the churn probability, the verdict against the current
threshold, and the recommended retention offer.
"""

import os

import gradio as gr
import httpx
import pandas as pd

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://localhost:8002")
DATA_PATH = os.environ.get("DATA_PATH", "data/churn.csv")

DEFAULT_THRESHOLD = 0.5

# Allowed values for the categorical fields (source of truth:
# services/preprocessing/app/features.py).
CHOICES = {
    "gender": ["Female", "Male"],
    "Partner": ["No", "Yes"],
    "Dependents": ["No", "Yes"],
    "PhoneService": ["No", "Yes"],
    "MultipleLines": ["No", "No phone service", "Yes"],
    "InternetService": ["DSL", "Fiber optic", "No"],
    "OnlineSecurity": ["No", "No internet service", "Yes"],
    "OnlineBackup": ["No", "No internet service", "Yes"],
    "DeviceProtection": ["No", "No internet service", "Yes"],
    "TechSupport": ["No", "No internet service", "Yes"],
    "StreamingTV": ["No", "No internet service", "Yes"],
    "StreamingMovies": ["No", "No internet service", "Yes"],
    "Contract": ["Month-to-month", "One year", "Two year"],
    "PaperlessBilling": ["No", "Yes"],
    "PaymentMethod": [
        "Bank transfer (automatic)",
        "Credit card (automatic)",
        "Electronic check",
        "Mailed check",
    ],
}

# Form layout: field order per section. ALL_FIELDS is the order of the
# values tuple passed to predict() and of the components in the UI.
CUSTOMER_INFO_FIELDS = ["gender", "SeniorCitizen", "Partner", "Dependents", "tenure"]
SERVICES_FIELDS = [
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
]
CONTRACT_BILLING_FIELDS = [
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
]
ALL_FIELDS = CUSTOMER_INFO_FIELDS + SERVICES_FIELDS + CONTRACT_BILLING_FIELDS

NO_OFFER_MESSAGE = "No offer — churn score below threshold"


def load_example() -> dict:
    """Returns one random row of the dataset as a dict of the 19 fields
    (Churn and customerID excluded). Used to pre-fill the form, so the
    example differs on each page load."""
    df = pd.read_csv(DATA_PATH)
    df = df.drop(columns=["Churn", "customerID"], errors="ignore")
    row = df.sample(n=1).iloc[0]
    example = {}
    for field in ALL_FIELDS:
        value = row[field]
        if field in ("SeniorCitizen", "tenure"):
            example[field] = int(value)
        elif field in ("MonthlyCharges", "TotalCharges"):
            # TotalCharges may be blank in the CSV (-> NaN); the
            # preprocessor coerces missing values to 0.
            example[field] = 0.0 if pd.isna(value) else float(value)
        else:
            example[field] = str(value)
    return example


def load_example_values() -> tuple:
    """load_example() shaped for Gradio: values in ALL_FIELDS order."""
    example = load_example()
    return tuple(example[field] for field in ALL_FIELDS)


def build_payload(values) -> dict:
    """Maps the form values (ALL_FIELDS order) to the API payload."""
    return dict(zip(ALL_FIELDS, values))


def get_threshold() -> float:
    """Fetches the current churn threshold from the inference service;
    falls back to 0.5 if unreachable."""
    try:
        resp = httpx.get(f"{INFERENCE_URL}/health", timeout=5)
        return float(resp.json()["threshold"])
    except Exception:
        return DEFAULT_THRESHOLD


def format_result(probability: float, offer: str, threshold: float) -> tuple:
    """Builds the (probability, verdict markdown, offer text) outputs."""
    verdict = "Churn likely" if probability >= threshold else "Churn unlikely"
    verdict_md = (
        f"### {verdict}\n"
        f"Churn probability **{probability:.1%}** "
        f"(threshold: {threshold:.2f})"
    )
    offer_text = NO_OFFER_MESSAGE if offer == "no_offer" else offer
    return probability, verdict_md, offer_text


def _error_result(message: str) -> tuple:
    return 0.0, f"### Error\n{message}", ""


def predict(*values) -> tuple:
    """Sends the form values to the inference service and returns the
    result components. API/network errors become user-facing messages
    (no stack traces)."""
    payload = build_payload(values)
    threshold = get_threshold()
    try:
        resp = httpx.post(f"{INFERENCE_URL}/predict", json=payload, timeout=10)
    except httpx.TimeoutException:
        return _error_result(
            f"The inference service at {INFERENCE_URL} timed out. "
            "Please try again."
        )
    except httpx.RequestError:
        return _error_result(
            f"Could not reach the inference service at {INFERENCE_URL}. "
            "Make sure it is running."
        )
    if resp.status_code == 422:
        return _error_result(
            "The inference service rejected the input (HTTP 422). "
            "Please check the form values."
        )
    if resp.status_code != 200:
        return _error_result(
            f"The inference service returned an unexpected error "
            f"(HTTP {resp.status_code})."
        )
    body = resp.json()
    return format_result(body["churn_probability"], body["recommended_offer"], threshold)


def _field_component(field: str):
    """Creates the form component for one field."""
    if field in CHOICES:
        return gr.Dropdown(choices=CHOICES[field], value=CHOICES[field][0], label=field)
    if field == "SeniorCitizen":
        return gr.Dropdown(choices=[0, 1], value=0, label=field)
    if field == "tenure":
        return gr.Slider(0, 72, step=1, value=12, label="tenure (months)")
    if field == "MonthlyCharges":
        return gr.Number(value=70.0, label="MonthlyCharges ($)")
    return gr.Number(value=1000.0, label="TotalCharges ($)")


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Telco Churn — Retention Demo") as demo:
        gr.Markdown("# Telco Churn — Retention Demo")
        gr.Markdown(
            "Portfolio demo of a telecom churn-prediction platform. "
            "The model scores a customer's risk of leaving, and when the "
            "score exceeds the decision threshold, a retention offer is "
            "recommended. The form is pre-filled with a random customer "
            "from the dataset."
        )
        inputs = []
        with gr.Accordion("Customer info", open=True):
            for field in CUSTOMER_INFO_FIELDS:
                inputs.append(_field_component(field))
        with gr.Accordion("Services", open=False):
            for field in SERVICES_FIELDS:
                inputs.append(_field_component(field))
        with gr.Accordion("Contract & billing", open=False):
            for field in CONTRACT_BILLING_FIELDS:
                inputs.append(_field_component(field))

        predict_btn = gr.Button("Predict", variant="primary")
        probability_out = gr.Slider(
            0, 1, step=0.001, value=0.0,
            label="Churn probability", interactive=False,
        )
        verdict_out = gr.Markdown()
        offer_out = gr.Textbox(label="Recommended offer", interactive=False)

        demo.load(load_example_values, outputs=inputs)
        predict_btn.click(
            predict, inputs=inputs,
            outputs=[probability_out, verdict_out, offer_out],
        )
    return demo


demo = build_ui()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
