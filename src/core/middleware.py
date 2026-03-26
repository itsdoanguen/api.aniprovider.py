import logging
import time
import uuid

from django.conf import settings
from django.http import JsonResponse

from django.utils.deprecation import MiddlewareMixin

from core.request_context import set_request_id

logger = logging.getLogger(__name__)


class RequestIDMiddleware(MiddlewareMixin):
    header_name = "HTTP_X_REQUEST_ID"

    def process_request(self, request):
        request_id = request.META.get(self.header_name) or str(uuid.uuid4())
        request.request_id = request_id
        request._started_at = time.perf_counter()
        set_request_id(request_id)

        # Public endpoints that don't require API key
        public_paths = {"/api/docs/", "/api/redoc/", "/api/schema/"}
        is_public = any(request.path.startswith(path) for path in public_paths)

        api_key = getattr(settings, "ANIPROVIDER_API_KEY", "").strip()
        if api_key and request.path.startswith("/api/") and not is_public:
            provided = (request.headers.get("X-API-Key") or "").strip()
            if provided != api_key:
                return JsonResponse(
                    {
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Invalid API key",
                            "request_id": request_id,
                        }
                    },
                    status=401,
                )

    def process_response(self, request, response):
        request_id = getattr(request, "request_id", None)
        if request_id:
            response["X-Request-ID"] = request_id

        started_at = getattr(request, "_started_at", None)
        if started_at is not None:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "request_complete method=%s path=%s status=%s duration_ms=%s",
                getattr(request, "method", "?"),
                getattr(request, "path", "?"),
                getattr(response, "status_code", "?"),
                duration_ms,
            )

        set_request_id(None)
        return response
