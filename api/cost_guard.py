"""
Cost guard — theo dõi chi phí OpenAI API ước tính theo ngày và chặn request
mới khi vượt ngân sách (DAILY_COST_LIMIT_USD).

Dùng Redis (nếu REDIS_URL được set, vd. trong docker-compose) để đếm chia sẻ
giữa nhiều worker; fallback in-memory cho dev/single-worker.
"""

import logging
import time

from .config import settings

logger = logging.getLogger("api.cost_guard")

_memory_store: dict[str, float] = {}
_redis_client = None
if settings.redis_url:
    import redis

    _redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def _today_key() -> str:
    return f"cost:{time.strftime('%Y-%m-%d', time.gmtime())}"


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * settings.price_input_per_1m
        + completion_tokens / 1_000_000 * settings.price_output_per_1m
    )


def get_today_cost_usd() -> float:
    key = _today_key()
    if _redis_client is not None:
        val = _redis_client.get(key)
        return float(val) if val else 0.0
    return _memory_store.get(key, 0.0)


def add_cost_usd(amount: float) -> float:
    """Cộng `amount` USD vào tổng chi phí hôm nay, trả về tổng mới."""
    key = _today_key()
    if _redis_client is not None:
        new_total = _redis_client.incrbyfloat(key, amount)
        _redis_client.expire(key, 60 * 60 * 48)  # giữ 2 ngày, đủ để debug
        return float(new_total)
    new_total = _memory_store.get(key, 0.0) + amount
    _memory_store[key] = new_total
    return new_total


def budget_exceeded() -> bool:
    return get_today_cost_usd() >= settings.daily_cost_limit_usd
