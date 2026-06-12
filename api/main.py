"""
FastAPI backend cho demo chatbot — bọc generate_with_citation() (Task 10)
thành một REST endpoint để web UI tĩnh (GitHub Pages) gọi tới qua HTTP.

Production-readiness:
    - /health  : liveness probe (process còn sống)
    - /ready   : readiness probe (kết nối Weaviate OK)
    - X-API-Key: auth tuỳ chọn cho /chat (bật khi set API_KEY)
    - Rate limit: chặn spam theo IP (RATE_LIMIT, mặc định 20/minute)
    - Cost guard: chặn khi chi phí OpenAI ước tính/ngày vượt DAILY_COST_LIMIT_USD
    - Structured (JSON) logging cho mọi request
    - Graceful shutdown: đóng Weaviate client khi process dừng
"""

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings
from .cost_guard import add_cost_usd, budget_exceeded, estimate_cost_usd, get_today_cost_usd
from .logging_config import setup_logging
from src.task5_semantic_search import _get_model as _get_embedding_model
from src.task6_lexical_search import _load_corpus
from src.task7_reranking import _get_reranker
from src.task10_generation import generate_with_citation, generate_with_citation_stream
from src.weaviate_client import connect_weaviate

setup_logging()
logger = logging.getLogger("api")

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url or "memory://")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API starting up")
    # Tải sẵn embedding model, reranker, và BM25 corpus khi container khởi
    # động — lần /chat đầu tiên của người dùng mất ~45s vì các model này được
    # tải từ HuggingFace Hub theo kiểu lazy (chỉ tải khi gọi lần đầu). Preload
    # ở đây để chi phí đó xảy ra lúc start container, không phải lúc người
    # dùng chờ trả lời.
    try:
        _get_embedding_model()
        _get_reranker()
        _load_corpus()
        logger.info("models and corpus preloaded")
    except Exception as e:
        logger.warning("model preload failed (will lazy-load on first request): %s", e)
    yield
    logger.info("API shutting down (graceful)")


app = FastAPI(title="LuậtMaTuý AI — Chat API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: web UI host trên domain khác (GitHub Pages) cần được phép gọi API này
# từ trình duyệt. Đọc danh sách origin từ env để đổi domain khi deploy mà
# không cần sửa code; mặc định "*" để tiện chạy/test cục bộ.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": get_remote_address(request),
        },
    )
    return response


class ChatRequest(BaseModel):
    query: str


# =============================================================================
# Health / readiness
# =============================================================================

@app.get("/")
def root():
    return {"status": "ok", "service": "luatmatuy-api"}


@app.get("/health")
def health():
    """Liveness probe — process còn chạy được thì luôn 200."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe — kiểm tra kết nối tới Weaviate (phụ thuộc bắt buộc
    của pipeline retrieval). Trả 503 nếu chưa sẵn sàng nhận traffic."""
    try:
        client = connect_weaviate()
        ok = client.is_ready()
        client.close()
        if not ok:
            raise RuntimeError("Weaviate not ready")
        return {"status": "ready"}
    except Exception as e:
        logger.warning("readiness check failed: %s", e)
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not ready"})


# =============================================================================
# Auth
# =============================================================================

async def require_api_key(request: Request):
    """Nếu API_KEY được cấu hình, client phải gửi header X-API-Key khớp.
    Nếu API_KEY không set (mặc định), endpoint mở công khai — giữ demo
    public hoạt động như hiện tại mà không cần đổi frontend."""
    if not settings.api_key:
        return
    if request.headers.get("X-API-Key") != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


# =============================================================================
# Chat
# =============================================================================

@app.post("/chat", dependencies=[Depends(require_api_key)])
@limiter.limit(settings.rate_limit)
def chat(req: ChatRequest, request: Request):
    if budget_exceeded():
        logger.warning("daily cost budget exceeded, rejecting request")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hệ thống đã đạt giới hạn chi phí trong ngày. Vui lòng thử lại sau.",
        )

    result = generate_with_citation(req.query)

    usage = result.get("usage", {})
    cost = estimate_cost_usd(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    total_today = add_cost_usd(cost)
    logger.info(
        "chat usage",
        extra={"path": "/chat", "method": "POST", "status_code": 200, "duration_ms": 0, "client_ip": get_remote_address(request)},
    )
    logger.debug("estimated cost: $%.6f (today total: $%.4f)", cost, total_today)

    return {
        "answer": result["answer"],
        # Chỉ trả về phần thiết yếu cho UI hiển thị citation (source/doc_type/
        # score) — tránh gửi nguyên văn nội dung chunk (có thể dài) qua API.
        "sources": [
            {
                "source": chunk.get("metadata", {}).get("source", ""),
                "doc_type": chunk.get("metadata", {}).get("doc_type", ""),
                "score": chunk.get("score"),
            }
            for chunk in result["sources"]
        ],
        "retrieval_source": result["retrieval_source"],
    }


# =============================================================================
# Chat (streaming)
# =============================================================================

@app.post("/chat/stream", dependencies=[Depends(require_api_key)])
@limiter.limit(settings.rate_limit)
def chat_stream(req: ChatRequest, request: Request):
    """Server-Sent Events: trả từng đoạn câu trả lời ngay khi sinh ra, thay vì
    bắt người dùng chờ toàn bộ response (~vài giây) mới thấy gì."""
    if budget_exceeded():
        logger.warning("daily cost budget exceeded, rejecting request")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hệ thống đã đạt giới hạn chi phí trong ngày. Vui lòng thử lại sau.",
        )

    client_ip = get_remote_address(request)

    def event_stream():
        for item in generate_with_citation_stream(req.query):
            if isinstance(item, str):
                yield f"data: {json.dumps({'token': item})}\n\n"
            else:
                usage = item.get("usage", {})
                cost = estimate_cost_usd(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                total_today = add_cost_usd(cost)
                logger.info(
                    "chat usage",
                    extra={"path": "/chat/stream", "method": "POST", "status_code": 200, "duration_ms": 0, "client_ip": client_ip},
                )
                logger.debug("estimated cost: $%.6f (today total: $%.4f)", cost, total_today)

                sources = [
                    {
                        "source": chunk.get("metadata", {}).get("source", ""),
                        "doc_type": chunk.get("metadata", {}).get("doc_type", ""),
                        "score": chunk.get("score"),
                    }
                    for chunk in item.get("sources", [])
                ]
                done_payload = {"done": True, "sources": sources, "retrieval_source": item.get("retrieval_source")}
                yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
