FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for soundfile (libsndfile)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Copy project and install with audio extras
COPY . .
RUN pip install --no-cache-dir ".[audio]"

# Default transport: streamable-http on 0.0.0.0:8000
EXPOSE 8000
ENTRYPOINT ["sample-library-manager"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
