# LuậtMaTuý AI — RAG Chatbot Pháp Luật Ma Túy

Pipeline RAG (Retrieval-Augmented Generation) trả lời câu hỏi về pháp luật
phòng, chống ma túy và tin tức liên quan, có trích dẫn nguồn (citation).

## Sản Phẩm Cuối — Live Demo

| Sản phẩm | URL |
|---|---|
| Live Demo (GitHub Pages) | https://oggishi.github.io/Day08_RAG_pipeline_cohort2 |
| Backend API (Render) | https://luatmatuy-api.onrender.com |
| Frontend (Render) | https://luatmatuy-web.onrender.com |

## Kiến Trúc Hệ Thống

```
GitHub repo (push to main)
   ├─ .github/workflows/deploy-frontend.yml → GitHub Pages (host static web/)
   └─ .github/workflows/deploy-backend.yml  → Hugging Face Space (Docker)
                                                    │
   web UI (GitHub Pages, HTML/CSS/JS)               │
        │  fetch POST /chat { query }               │
        └──────────────────────────────────────────┘
                                                    │
                                          FastAPI app (api/main.py)
                                                    │
                                       generate_with_citation()  (Task 10)
                                                    │
                                          retrieve()  (Task 9 — hybrid pipeline)
                                          ┌─────────┼──────────┬──────────────┐
                                          │         │          │              │
                                   semantic search  lexical   rerank     PageIndex
                                   (Weaviate Cloud) (BM25,    (cross-   (vectorless,
                                                     local .md) encoder)  fallback khi
                                                                          score < 0.3)
                                                    │
                                          OpenAI gpt-4o-mini → answer + citations
```

## Pipeline (Task 1-10)

| Task | File | Mô tả |
|---|---|---|
| 1 | `src/task1_collect_legal_docs.py` | Thu thập văn bản pháp luật ma túy |
| 2 | `src/task2_crawl_news.py` | Crawl tin tức liên quan |
| 3 | `src/task3_convert_markdown.py` | Chuẩn hoá tài liệu sang Markdown |
| 4 | `src/task4_chunking_indexing.py` | Chunking + indexing vào Weaviate |
| 5 | `src/task5_semantic_search.py` | Semantic search (embedding `BAAI/bge-m3`) |
| 6 | `src/task6_lexical_search.py` | Lexical search (BM25 + underthesea) |
| 7 | `src/task7_reranking.py` | Reranking (cross-encoder `BAAI/bge-reranker-v2-m3`) |
| 8 | `src/task8_pageindex_vectorless.py` | PageIndex — fallback vectorless khi điểm retrieval thấp |
| 9 | `src/task9_retrieval_pipeline.py` | Hybrid retrieval pipeline (kết hợp 5-8) |
| 10 | `src/task10_generation.py` | Generation có citation (OpenAI gpt-4o-mini) |

## Chạy Local

```bash
# Cài đặt dependencies
pip install -r requirements.txt

# Cấu hình .env (xem .env.example): OPENAI_API_KEY, WEAVIATE_URL,
# WEAVIATE_API_KEY, JINA_API_KEY, PAGEINDEX_API_KEY

# Chạy backend API (FastAPI)
uvicorn api.main:app --reload --port 8000

# Mở web/index.html trong trình duyệt (chỉnh API_BASE trong web/app.js
# trỏ về http://localhost:8000 khi test local)
```

## Chạy Bằng Docker (production-like)

```bash
# Build + run API (cổng 7860) cùng Redis (rate limit + cost guard)
docker compose up --build

# Kiểm tra
curl http://localhost:7860/health   # liveness
curl http://localhost:7860/ready    # readiness (kiểm tra Weaviate)
```

Deploy lên Render bằng `render.yaml` (Blueprint) hoặc lên Hugging Face Spaces
(Docker SDK, xem `api/SPACE_README.md`).

## API Endpoints (`api/main.py`)

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Liveness check, luôn trả 200 |
| `GET /ready` | Readiness check, kiểm tra kết nối Weaviate |
| `POST /chat` | `{"query": "..."}` → `{"answer", "sources", "retrieval_source"}` |

Bảo mật: API Key tuỳ chọn qua header `X-API-Key` (biến môi trường `API_KEY`),
rate limiting qua `slowapi` (`RATE_LIMIT`), cost guard chặn request khi vượt
`DAILY_COST_LIMIT_USD`.

## Production Readiness

Kiểm tra bằng `python check_production_ready.py`:

```
=======================================================
  Production Readiness Check — Day 12 Lab
=======================================================

📁 Required Files
  ✅ Dockerfile exists
  ✅ docker-compose.yml exists
  ✅ .dockerignore exists
  ✅ .env.example exists
  ✅ requirements.txt exists
  ✅ railway.toml or render.yaml exists

🔒 Security
  ✅ .env in .gitignore
  ✅ No hardcoded secrets in code

🌐 API Endpoints (code check)
  ✅ /health endpoint defined
  ✅ /ready endpoint defined
  ✅ Authentication implemented
  ✅ Rate limiting implemented
  ✅ Graceful shutdown (SIGTERM)
  ✅ Structured logging (JSON)

🐳 Docker
  ✅ Multi-stage build
  ✅ Non-root user
  ✅ HEALTHCHECK instruction
  ✅ Slim base image
  ✅ .dockerignore covers .env
  ✅ .dockerignore covers __pycache__

=======================================================
  Result: 20/20 checks passed (100%)
  🎉 PRODUCTION READY! Deploy nào!
=======================================================
```

> **Lưu ý kích thước image:** Docker image build ra ~2.2GB (chưa đạt mục tiêu
> < 500MB) vì pipeline retrieval/reranking (Task 5, Task 7) dùng các model
> embedding/cross-encoder local qua `sentence-transformers`/`transformers`/
> `torch` — đây là lựa chọn kỹ thuật cốt lõi của pipeline. Xem
> `group_project/README.md` để biết chi tiết.

## Bài Tập Nhóm

Xem [group_project/README.md](group_project/README.md) cho phân công công
việc, kiến trúc triển khai và evaluation pipeline (DeepEval).
