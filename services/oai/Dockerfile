# Dockerfile for Wormhole OAI
# OpenAI-compatible API server

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY wormhole-oai.py .
COPY send.py .
COPY agent_workflow.py .
COPY template_composer.py .
COPY prompt_utils.py .
COPY dump_raw.py .

# Create directories for data and templates
RUN mkdir -p /app/data /app/templates

# Create non-root user
RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app
USER wormhole

# Expose API port
EXPOSE 11434

# Health check - verify API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/version')" || exit 1

# Run API server
CMD ["python", "wormhole-oai.py"]
