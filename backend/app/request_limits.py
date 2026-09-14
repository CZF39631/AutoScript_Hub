"""JSON 控制接口先限流式请求体，再交给 Pydantic 解码。"""
from fastapi import HTTPException
from fastapi.routing import APIRoute


class BoundedJsonRoute(APIRoute):
    # 允许受限日志里的 JSON 转义开销；各字段另有更小的 UTF-8 上限。
    max_body_bytes = 512 * 1024

    def limit_request_body(self, request):
        return True

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method in {'POST', 'PUT', 'PATCH'} and self.limit_request_body(request):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > self.max_body_bytes:
                        raise HTTPException(413, '请求内容超过允许的字节上限')
                    body.extend(chunk)
                request._body = bytes(body)
            response = await handler(request)
            response.headers['Cache-Control'] = 'no-store'
            return response
        return bounded


class RunJsonRoute(BoundedJsonRoute):
    # 兼容旧日志分块中的 JSON 转义开销。
    max_body_bytes = 1024 * 1024

    def limit_request_body(self, request):
        # 1.2.4 sends the entire unacknowledged log, not bounded chunks. Its
        # endpoint authenticates/authorizes BEFORE reading JSON; retain that
        # legacy payload contract without weakening new task/diagnostic limits.
        return not (self.path == '/api/runs/{run_id}/log/chunk' and request.method == 'POST')
