FROM python:3.11-slim

ENV PYTHONUNBUFFERED True

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080

# Start Uvicorn and bind to Cloud Run's port
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"
