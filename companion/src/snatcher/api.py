from __future__ import annotations

import hmac
import secrets
import shutil
from contextlib import asynccontextmanager

import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import __version__
from .config import ConfigStore
from .deepgram import DeepgramClient
from .errors import SnatcherError
from .jobs import JobManager
from .models import CaptureRequest, HealthResponse, JobRecord, PairRequest
from .notion import NotionClient
from .secrets import SecretStore


def create_app(
    *,
    config_store: ConfigStore | None = None,
    secret_store: SecretStore | None = None,
) -> FastAPI:
    config_store = config_store or ConfigStore()
    config = config_store.load()
    secret_store = secret_store or SecretStore()
    pairing_code = secrets.token_hex(4)
    manager = JobManager(config, config_store, secret_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.cleanup_expired()
        yield

    app = FastAPI(
        title="Video Graphic Snatcher Companion",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.config_store = config_store
    app.state.secret_store = secret_store
    app.state.job_manager = manager
    app.state.pairing_code = pairing_code

    @app.middleware("http")
    async def extension_cors(request: Request, call_next):
        origin = request.headers.get("origin", "")
        allowed = origin.startswith("chrome-extension://") or origin in {
            f"http://127.0.0.1:{config.port}",
            f"http://localhost:{config.port}",
        }
        if request.method == "OPTIONS":
            response: Response = Response(status_code=204 if allowed else 403)
        else:
            response = await call_next(request)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Snatcher-Token"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    def require_token(
        x_snatcher_token: str | None = Header(default=None),
    ) -> None:
        if not x_snatcher_token or not hmac.compare_digest(x_snatcher_token, config.pair_token):
            raise HTTPException(status_code=401, detail="Pair the extension first.")

    @app.exception_handler(SnatcherError)
    async def snatcher_error_handler(_request: Request, exc: SnatcherError):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                }
            },
        )

    @app.get("/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            ffmpeg=shutil.which("ffmpeg") is not None,
            ffprobe=shutil.which("ffprobe") is not None,
            yt_dlp=bool(yt_dlp.version.__version__),
            deepgram_configured=bool(secret_store.get_deepgram_key()),
            notion_configured=bool(secret_store.get_notion_token())
            and bool(config.notion_parent_page_id),
            notion_database_configured=bool(config.notion_data_source_id),
            pairing_required=True,
        )

    @app.post("/v1/pair")
    async def pair(payload: PairRequest) -> dict[str, str]:
        if not hmac.compare_digest(payload.code.lower(), pairing_code.lower()):
            raise HTTPException(status_code=401, detail="Incorrect pairing code.")
        return {"token": config.pair_token}

    @app.get("/v1/settings", dependencies=[Depends(require_token)])
    async def settings() -> dict:
        return config.public_dict()

    @app.post("/v1/setup/deepgram/test", dependencies=[Depends(require_token)])
    async def test_deepgram() -> dict[str, str]:
        key = secret_store.get_deepgram_key()
        if not key:
            raise SnatcherError("Deepgram is not configured.", code="deepgram_not_configured")
        await DeepgramClient(key).test_connection()
        return {"status": "ok"}

    @app.post("/v1/setup/notion/test", dependencies=[Depends(require_token)])
    async def test_notion() -> dict[str, str]:
        token = secret_store.get_notion_token()
        if not token:
            raise SnatcherError("Notion is not configured.", code="notion_not_configured")
        await NotionClient(token, config, config_store).test_connection()
        return {"status": "ok"}

    @app.post("/v1/setup/notion/bootstrap", dependencies=[Depends(require_token)])
    async def bootstrap_notion() -> dict[str, str | None]:
        token = secret_store.get_notion_token()
        if not token:
            raise SnatcherError("Notion is not configured.", code="notion_not_configured")
        data_source_id = await NotionClient(token, config, config_store).bootstrap_database()
        return {
            "status": "ok",
            "data_source_id": data_source_id,
            "database_url": config.notion_database_url,
        }

    @app.post(
        "/v1/jobs",
        response_model=JobRecord,
        dependencies=[Depends(require_token)],
    )
    async def create_job(payload: CaptureRequest) -> JobRecord:
        return manager.create(payload)

    @app.get(
        "/v1/jobs/recent",
        response_model=list[JobRecord],
        dependencies=[Depends(require_token)],
    )
    async def recent_jobs() -> list[JobRecord]:
        return manager.recent()

    @app.get(
        "/v1/jobs/{job_id}",
        response_model=JobRecord,
        dependencies=[Depends(require_token)],
    )
    async def get_job(job_id: str) -> JobRecord:
        try:
            return manager.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    @app.post(
        "/v1/jobs/{job_id}/cancel",
        response_model=JobRecord,
        dependencies=[Depends(require_token)],
    )
    async def cancel_job(job_id: str) -> JobRecord:
        try:
            return manager.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    @app.post(
        "/v1/jobs/{job_id}/retry",
        response_model=JobRecord,
        dependencies=[Depends(require_token)],
    )
    async def retry_job(job_id: str) -> JobRecord:
        try:
            return manager.retry(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found.") from exc

    return app
