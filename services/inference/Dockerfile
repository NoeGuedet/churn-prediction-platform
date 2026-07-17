FROM python:3.14-slim

# libgomp1 : runtime OpenMP requis par XGBoost sur Debian
# (équivalent de libomp sur macOS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/inference/requirements.txt .
# xgboost avec --no-deps : son wheel Linux dépend de librairies nvidia/CUDA
# (~400 Mo) inutiles pour de l'inférence CPU. numpy/scipy (ses vraies
# dépendances) sont déjà fournies par scikit-learn.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps xgboost==3.3.0

COPY services/inference/app ./app
COPY models/churn_model.pkl ./models/churn_model.pkl
COPY models/offer_model.pkl ./models/offer_model.pkl

ENV MODELS_DIR=models
ENV WORKERS=2

EXPOSE 8002

CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS} -b 0.0.0.0:8002
