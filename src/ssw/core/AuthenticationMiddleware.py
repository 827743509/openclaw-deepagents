from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuthenticationMiddleware(BaseHTTPMiddleware):

    def __init__(self, app):
        super().__init__(app)


    async def dispatch(self, request: Request, call_next):
        #解析token获取user_id
        user_id = "salt-soda-water"

        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="用户未登录"
            )
        # 放入当前请求上下文
        request.state.user_id = user_id

        return await call_next(request)
