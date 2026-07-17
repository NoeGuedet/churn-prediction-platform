FROM python:3.14-slim

WORKDIR /app

COPY services/preprocessing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/preprocessing/app ./app
COPY models/preprocessor.pkl ./models/preprocessor.pkl

ENV MODELS_DIR=models
ENV WORKERS=2

EXPOSE 8001

CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS} -b 0.0.0.0:8001
