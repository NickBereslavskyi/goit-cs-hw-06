FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (optional but handy for network tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --no-cache-dir pymongo

# Copy application
COPY . /app/

EXPOSE 3000 5000

CMD ["python", "main.py"]
