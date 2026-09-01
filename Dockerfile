FROM python:3.12-slim

# Install Tesseract OCR
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Render uses port 10000
EXPOSE 10000

# Start Flask with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]