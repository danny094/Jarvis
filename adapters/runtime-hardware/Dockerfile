FROM python:3.12-slim

WORKDIR /app

COPY adapters/runtime-hardware/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY adapters/runtime-hardware/main.py /app/main.py
COPY adapters/runtime-hardware/runtime_hardware /app/runtime_hardware

RUN mkdir -p /app/data/config /app/data/state

EXPOSE 8420

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8420", "--log-level", "info"]
