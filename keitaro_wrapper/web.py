from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from keitaro_wrapper.campaigns import Campaigns, CreateCampaign
from keitaro_wrapper.config import Settings
from keitaro_wrapper.database import create_sessions
from keitaro_wrapper.editor import CampaignView, Edit, Editor, Revision, StreamView
from keitaro_wrapper.errors import AppError
from keitaro_wrapper.keitaro import Campaign, Keitaro, PositiveId, Reference
from keitaro_wrapper.ui import Interface


def create_app(settings: Settings, transport: httpx.BaseTransport | None = None) -> FastAPI:
    client = httpx.Client(
        base_url=f"{str(settings.keitaro_url).rstrip('/')}/admin_api/v1/",
        headers={"Api-Key": settings.keitaro_api_key.get_secret_value()},
        timeout=httpx.Timeout(15, connect=5),
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    )
    sessions = create_sessions(settings.database_url)
    campaigns = Campaigns(Keitaro(client), settings.campaign_prefix)
    editor = Editor(campaigns, sessions)
    interface = Interface(campaigns, editor)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            client.close()
            sessions.kw["bind"].dispose()

    app = FastAPI(title="Keitaro Wrapper", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @app.middleware("http")
    async def require_same_origin(request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and origin is not None
            and origin != str(request.base_url).rstrip("/")
        ):
            return JSONResponse({"detail": "Cross-origin changes are not allowed."}, 403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith(("/api/", "/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'; img-src 'self' data:; "
                "style-src 'self' 'sha256-UP0QZg7irvSMvOBz9mH2PIIE28+57UiavRfeVea0l3g='"
            )
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, error: AppError) -> Response:
        if request.url.path.startswith("/ui/"):
            return interface.error(request, str(error), error.status)
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.exception_handler(Exception)
    @app.exception_handler(SQLAlchemyError)
    async def server_error(request: Request, error: Exception) -> Response:
        if isinstance(error, SQLAlchemyError):
            status = 503
            message = "Ошибка локальной базы данных. Проверьте состояние кампании перед повтором."
        else:
            status = 500
            message = "Внутренняя ошибка приложения. Проверьте состояние кампании перед повтором."
        if request.url.path == "/":
            response = interface.render(
                request, "editor.html", prefix=settings.campaign_prefix,
                campaign_id=request.query_params.get("campaign_id"), message=message,
            )
            response.status_code = status
            return response
        return await app_error(request, AppError(status, message))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> Response:
        if request.url.path.startswith("/ui/"):
            hints = {
                "country": "Введите двухбуквенный код страны, например AU.",
                "offer_id": "Выберите оффер из списка или введите его числовой ID.",
                "name": "Введите название кампании длиной до 100 символов.",
                "domain_id": "Выберите домен.",
                "group_id": "Выберите группу.",
                "traffic_source_id": "Выберите источник.",
                "campaign_id": "Введите положительный числовой ID кампании.",
            }
            messages = [
                hints[field] for item in error.errors()
                if item["loc"] and (field := str(item["loc"][-1])) in hints
            ]
            return interface.error(
                request, " ".join(dict.fromkeys(messages)) or "Проверьте поля формы.", 422
            )
        details = [{"loc": item["loc"], "msg": item["msg"]} for item in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    interface.mount(app)

    @app.get("/api/lookups")
    def lookups() -> dict[str, list[Reference]]:
        return campaigns.lookups()

    @app.get("/api/offers")
    def offers(q: Annotated[str, Query(min_length=1, max_length=100)]) -> list[Reference]:
        return campaigns.search_offers(q.strip())

    @app.post("/api/campaigns", status_code=201)
    def create_campaign(data: CreateCampaign) -> Campaign:
        return campaigns.create(data)

    @app.post("/api/campaigns/{campaign_id}/sync")
    def sync(campaign_id: PositiveId) -> CampaignView:
        return editor.sync(campaign_id)

    @app.post("/api/streams/{stream_id}/draft")
    def edit(stream_id: PositiveId, data: Edit) -> StreamView:
        return editor.edit(stream_id, data)

    @app.post("/api/streams/{stream_id}/cancel")
    def cancel(stream_id: PositiveId, data: Revision) -> StreamView:
        return editor.cancel(stream_id, data)

    @app.post("/api/streams/{stream_id}/publish")
    def publish(stream_id: PositiveId, data: Revision) -> StreamView:
        return editor.publish(stream_id, data)

    return app
