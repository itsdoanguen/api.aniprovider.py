from dataclasses import dataclass

from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.error_codes import ErrorCode
from core.request_context import get_request_id


@dataclass
class ErrorPayload:
    code: str
    message: str
    details: dict | None = None


class AniProviderException(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_code = ErrorCode.INTERNAL_ERROR
    default_detail = "Internal server error"

    def __init__(self, detail=None, code=None, details=None):
        super().__init__(detail=detail, code=code)
        self.details = details


class InvalidInputException(AniProviderException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = ErrorCode.INVALID_INPUT
    default_detail = "Invalid input"


class UpstreamTimeoutException(AniProviderException):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_code = ErrorCode.UPSTREAM_TIMEOUT
    default_detail = "Upstream timeout"


class UpstreamServiceException(AniProviderException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = ErrorCode.UPSTREAM_BAD_RESPONSE
    default_detail = "Upstream service error"


class ServiceUnavailableException(AniProviderException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = ErrorCode.SERVICE_UNAVAILABLE
    default_detail = "Service unavailable"


def _build_error_response(error: ErrorPayload, status_code: int) -> Response:
    payload = {
        "error": {
            "code": error.code,
            "message": error.message,
            "request_id": get_request_id(),
        }
    }
    if error.details is not None:
        payload["error"]["details"] = error.details

    return Response(
        payload,
        status=status_code,
    )


def global_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, ValidationError):
        return _build_error_response(
            ErrorPayload(code=ErrorCode.INVALID_INPUT, message="Invalid input"),
            status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, AniProviderException):
        code = exc.get_codes()
        if isinstance(code, list):
            code = code[0] if code else str(exc.default_code)
        if isinstance(code, dict):
            code = str(exc.default_code)

        message = exc.detail
        if not isinstance(message, str):
            message = str(message)

        error = ErrorPayload(code=str(code), message=message, details=exc.details)
        return _build_error_response(
            error,
            exc.status_code,
        )

    if response is not None:
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return _build_error_response(
                ErrorPayload(code=ErrorCode.NOT_FOUND, message="Resource not found"),
                status.HTTP_404_NOT_FOUND,
            )
        return response

    return _build_error_response(
        ErrorPayload(code=ErrorCode.INTERNAL_ERROR, message="Internal server error"),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
