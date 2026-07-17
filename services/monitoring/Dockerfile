FROM python:3.14-slim

WORKDIR /app

COPY services/monitoring/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/monitoring/app ./app

ENV WORKERS=1

EXPOSE 8003

CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS} -b 0.0.0.0:8003
