FROM python:3.12-slim

WORKDIR /app

# Install deps first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consumer.py .

# consumer.py is the entrypoint; env vars supplied by docker-compose
CMD ["python", "-u", "consumer.py"]
