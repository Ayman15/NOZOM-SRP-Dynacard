FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY api /app/api
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--app-dir", "/app/api", "--host", "0.0.0.0", "--port", "8000"]
