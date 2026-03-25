"""Entry-point for the Open Deep Research API server."""

import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from open_deep_research.new_endpoint import app, router


# ---------------------------------------------------------------------------
# ASGI Middleware: Normalize smart/curly quotes in JSON bodies
# ---------------------------------------------------------------------------
class SmartQuoteNormalizerMiddleware:
    """Raw ASGI middleware - converts Unicode smart quotes to ASCII before FastAPI parsing."""
    
    _QUOTE_MAP = str.maketrans({
        "\u201c": '"',  "\u201d": '"',  # Curly double quotes → straight
        "\u2018": "'",  "\u2019": "'",  # Curly single quotes → straight
    })

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Check if Content-Type is JSON
        is_json = any(
            b"json" in v.lower() 
            for k, v in scope.get("headers", []) 
            if k.lower() == b"content-type"
        )

        if not is_json:
            return await self.app(scope, receive, send)

        # Buffer the body
        body_parts = []
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                body_parts.append(msg.get("body", b""))
                if not msg.get("more_body", False):
                    break

        body = b"".join(body_parts)

        # Normalize quotes if needed
        try:
            text = body.lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="replace")
            body = text.translate(self._QUOTE_MAP).encode("utf-8")
        except Exception:
            pass  # Keep original on error

        # New receive callable that yields modified body
        sent = [False]
        async def receive_new():
            if not sent[0]:
                sent[0] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b""}

        return await self.app(scope, receive_new, send)


# Wrap app with quote normalizer
app = SmartQuoteNormalizerMiddleware(app)

# ---------------------------------------------------------------------------
# Middleware: CORS
# ---------------------------------------------------------------------------
app.app.add_middleware(  # .app accesses inner FastAPI instance
    CORSMiddleware,
    allow_origins=["*"],          # tighten to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.app.include_router(router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health-check
# ---------------------------------------------------------------------------
@app.app.get("/health", tags=["health"])
async def health() -> dict:
    """Return a simple liveness signal."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
