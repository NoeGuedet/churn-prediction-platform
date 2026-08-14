FROM python:3.14-slim

# libgomp1: OpenMP runtime required by XGBoost on Debian
# (equivalent of libomp on macOS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/inference/requirements.txt .
# xgboost with --no-deps: its Linux wheel depends on nvidia/CUDA
# libraries (~400 MB) that are useless for CPU inference. numpy/scipy
# (its real dependencies) are already provided by scikit-learn.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps xgboost==3.3.0

COPY services/inference/app ./app
COPY models/churn_model.pkl ./models/churn_model.pkl
COPY models/offer_model.pkl ./models/offer_model.pkl

ENV MODELS_DIR=models
ENV WORKERS=2

EXPOSE 8002

CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS} -b 0.0.0.0:8002
