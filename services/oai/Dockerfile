# Dockerfile for Wormhole OAI
# OpenAI-compatible API server

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY services/oai/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY services/oai/wormhole-oai.py .
COPY services/oai/send.py .
COPY services/oai/agent_workflow.py .
COPY services/oai/template_composer.py .
COPY services/oai/prompt_utils.py .
COPY services/oai/dump_raw.py .
COPY services/oai/create_conversation.js .
COPY services/oai/send_message.js .

# Create directories for data and templates
RUN mkdir -p /app/data /app/templates

# Create non-root user and set ownership
RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app

# Switch to non-root user
USER wormhole

# Expose API port
EXPOSE 11434

# Health check - verify API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/version')" || exit 1

# Run API server
CMD ["python", "wormhole-oai.py"]
