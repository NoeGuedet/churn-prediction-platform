FROM python:3.14-slim

WORKDIR /app

COPY services/segmentation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/segmentation/app ./app
# Source de vérité partagée pour les features (identique à l'entraînement).
COPY services/preprocessing/app/features.py ./app/features.py
COPY models/preprocessor.pkl ./models/preprocessor.pkl
COPY data/churn.csv ./data/churn.csv

WORKDIR /app/app
CMD ["python", "main.py"]
