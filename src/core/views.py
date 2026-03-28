from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def live(request):
    return JsonResponse({"status": "ok"}, status=200)


def ready(request):
    redis_enabled = bool(getattr(settings, "ANIPROVIDER_ENABLE_ASYNC_CRAWL", False))
    require_redis_ready = bool(getattr(settings, "ANIPROVIDER_REQUIRE_REDIS_READY", False))

    redis_ok = True
    if redis_enabled:
        redis_ok = _check_redis(settings.REDIS_URL)

    checks = {
        "database": _check_database(),
        "redis": redis_ok,
        "redis_enabled": redis_enabled,
        "redis_required": require_redis_ready,
    }

    healthy = checks["database"] and (not require_redis_ready or checks["redis"])
    status_code = 200 if healthy else 503
    return JsonResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status=status_code)


def _check_database() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:
        return False


def _check_redis(redis_url: str) -> bool:
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        return bool(client.ping())
    except Exception:
        return False
