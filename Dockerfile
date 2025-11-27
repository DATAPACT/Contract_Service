# Use an official Python runtime as a parent image
FROM python:3.11.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Expose port 80 for the application
EXPOSE 8866

# Run the application
CMD ["python", "-m", "uvicorn", "contract_service_api:app", "--host", "0.0.0.0", "--port", "8866"]
