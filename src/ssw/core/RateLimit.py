from fastapi import  Request, HTTPException
from functools import wraps

from ssw.core.RedisClient import redis_client



#固定窗口限流
async def check_rate_limit(request, limit) :
    user_id = request.state.user_id
    key = f"rate_limit:{user_id}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 60)
    if count > limit:
        return False
    return True

def rate_limit(limit: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):

            # 获取 Request
            request: Request | None = kwargs.get("http_request")

            if request is None:
                # 防止 Request 是位置参数
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is None:
                raise RuntimeError("接口必须声明 Request 参数")

            flag:bool = await check_rate_limit(request, limit)
            if not flag:
                raise HTTPException(
                    status_code=429,
                    detail="请求过于频繁"
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator