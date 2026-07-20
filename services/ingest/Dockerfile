FROM python:3.12-slim
WORKDIR /app
COPY ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY ingest /app/ingest
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/ingest/ingest.py"]
