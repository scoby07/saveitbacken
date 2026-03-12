FROM python:3.12-slim
 
# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
 
# Set working directory
WORKDIR /app
 
# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
# Copy app
COPY server.py .
 
# Run
CMD ["/bin/sh", "-c", "gunicorn server:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120"]
 
