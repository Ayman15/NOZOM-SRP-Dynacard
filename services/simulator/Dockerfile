FROM python:3.12-slim
WORKDIR /app
COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY simulator /app/simulator
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/simulator/simulator.py"]
