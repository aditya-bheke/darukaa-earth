FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Build and validate the knowledge base at image build time (also downloads the embedding model).
RUN LLM_PROVIDER=none python -m darukaa.kb.build

EXPOSE 8000 8501
# Default: FastAPI + the single-page front end (served at /app, "/" redirects there).
# For the Streamlit console instead:
#   docker run -p 8501:8501 --env-file .env darukaa-earth #     streamlit run app.py --server.address=0.0.0.0 --server.port=8501
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
