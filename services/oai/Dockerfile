FROM python:3.11-slim

WORKDIR /app

COPY services/oai/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/oai/wormhole-oai.py .
COPY services/oai/send.py .
COPY services/oai/agent_workflow.py .
COPY services/oai/template_composer.py .
COPY services/oai/prompt_utils.py .
COPY services/oai/dump_raw.py .
COPY services/oai/create_conversation.js .
COPY services/oai/send_message.js .
COPY services/oai/agent_prompts.yaml .

RUN mkdir -p /app/data /app/templates

RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app

USER wormhole

EXPOSE 11434

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/version')" || exit 1

CMD ["python", "wormhole-oai.py"]
