"""
Cấu hình API đọc từ environment variables — tập trung tại một nơi để dễ
audit/đổi khi deploy (Docker, Render, Hugging Face Spaces) mà không cần sửa
code.
"""

import os


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    # CORS — domain của web UI (GitHub Pages) được phép gọi API
    allowed_origins: list[str] = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    ]

    # API key auth — nếu API_KEY rỗng, /chat mở công khai (giữ demo public
    # hoạt động như hiện tại). Nếu set, client phải gửi header X-API-Key.
    api_key: str = os.getenv("API_KEY", "")

    # Rate limiting (slowapi) — cú pháp "<số>/<đơn vị>", vd "10/minute".
    rate_limit: str = os.getenv("RATE_LIMIT", "20/minute")

    # Cost guard — ngân sách USD/ngày cho OpenAI API (ước tính theo token
    # usage trả về từ response.usage). Khi vượt, /chat trả 429.
    daily_cost_limit_usd: float = _float("DAILY_COST_LIMIT_USD", 5.0)

    # gpt-4o-mini pricing (USD / 1M token) — dùng để ước tính cost guard.
    price_input_per_1m: float = _float("PRICE_INPUT_PER_1M_USD", 0.15)
    price_output_per_1m: float = _float("PRICE_OUTPUT_PER_1M_USD", 0.60)

    # Redis — lưu trạng thái rate limit + cost guard (chia sẻ giữa các
    # replica/worker). Nếu không set, fallback in-memory (chỉ phù hợp 1 worker).
    redis_url: str = os.getenv("REDIS_URL", "")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
