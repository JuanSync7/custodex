"""Request handlers."""


def ping(request: str) -> str:
    return request


def on_get(request: str) -> str:
    return request


class Router:
    def on_post(self, request: str) -> str:
        body = request.strip()
        return body

    # DELETE is idempotent.
    def on_delete(self, request: str) -> str:
        return request

    def dispatch(self, request: str, context: dict[str, str]) -> str:
        return context.get(request, request)
