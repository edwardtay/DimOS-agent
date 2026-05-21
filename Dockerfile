FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt fastapi uvicorn pydantic

COPY dimos_proto/ ./dimos_proto/

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

# ANTHROPIC_API_KEY must be passed at runtime:
#   docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... dimos-agent
CMD ["python", "-m", "dimos_proto.server"]
