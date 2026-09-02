"""统一异常 → HTTP 响应转换。

约定响应体：{"code": "<业务错误码>", "message": "<面向用户的描述>"}
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ssw.core.exceptions import AppException
from ssw.core.logging import get_logger

logger = get_logger(__name__)


async def _app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # 兜底：未被业务异常覆盖的错误，避免泄露堆栈给前端
    logger.exception("unhandled exception at %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "服务内部错误"},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, _app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
