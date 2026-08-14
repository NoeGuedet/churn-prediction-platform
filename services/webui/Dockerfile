FROM python:3.14-slim

WORKDIR /app

COPY services/webui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/webui/app.py .
COPY data/churn.csv data/churn.csv

ENV DATA_PATH=data/churn.csv

EXPOSE 7860

CMD python app.py
