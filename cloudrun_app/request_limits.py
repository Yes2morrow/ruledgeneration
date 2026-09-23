from starlette.responses import JSONResponse


class RequestSizeLimit:
    """Bound JSON bodies including chunked requests before Pydantic allocation."""
    def __init__(self, app, max_bytes=65536):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH'):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.max_bytes:
                return await JSONResponse({'detail': '请求内容过大'}, status_code=413)(scope, receive, send)
            chunks.append(message.get('body', b''))
            if not message.get('more_body', False):
                break
        consumed = False

        async def buffered_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        return await self.app(scope, buffered_receive, send)
