# Multi-stage build cho backend demo chatbot (FastAPI bọc generate_with_citation
# — Task 10). Đặt ở gốc repo vì Hugging Face Spaces (Docker SDK) mặc định build
# từ Dockerfile tại root.
#
# Stage 1 "builder": cài dependencies vào virtualenv riêng.
#   - Dùng requirements-api.txt (subset runtime-only, không có
#     crawl4ai/markitdown/langchain/streamlit/deepeval — chỉ cần cho data prep
#     offline, không cần để serve /chat).
#   - Cài torch bản CPU-only (--extra-index-url) — tránh các thư viện CUDA
#     (vài GB) không cần thiết khi serve trên CPU.
# Stage 2 "runtime": copy venv + mã nguồn cần thiết, không có build tool/cache
# → image cuối nhỏ hơn đáng kể so với build 1 stage từ requirements.txt đầy đủ.

FROM python:3.11-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-api.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-api.txt


FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Mã nguồn pipeline (Task 5-10) + dữ liệu chuẩn hoá cần ở runtime:
#   - task6_lexical_search xây BM25 corpus từ data/standardized/*.md
#   - task8_pageindex_vectorless đọc data/standardized/_pageindex_doc_map.json
COPY src/ ./src/
COPY data/standardized/ ./data/standardized/
COPY api/ ./api/

# Chạy bằng user non-root — giảm rủi ro nếu container bị compromise.
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Hugging Face Spaces (Docker SDK) mặc định expose cổng 7860.
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health')" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
