FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy segmentation service files
COPY config.py cost_engine.py segment.py ./

# Seed runner script will be created separately
COPY seed_and_run.py ./

CMD ["python", "-u", "seed_and_run.py"]
