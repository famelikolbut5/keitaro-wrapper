from contextlib import suppress
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from keitaro_wrapper.campaigns import Campaigns, CreateCampaign
from keitaro_wrapper.editor import CampaignView, Edit, Editor, Revision, StreamView
from keitaro_wrapper.errors import AppError
from keitaro_wrapper.keitaro import PositiveId, Reference

ROOT = Path(__file__).parent


class Interface:
    def __init__(self, campaigns: Campaigns, editor: Editor) -> None:
        self.campaigns = campaigns
        self.editor = editor
        self.templates = Jinja2Templates(directory=str(ROOT / "templates"))
        self.names: dict[int, str] = {}
        self.names_lock = Lock()

    def render(self, request: Request, template: str, **data: object) -> Response:
        return self.templates.TemplateResponse(request=request, name=template, context=data)

    def error(self, request: Request, message: str, status: int) -> Response:
        return self.templates.TemplateResponse(
            request=request,
            name="notice.html",
            context={"message": message, "tone": "error"},
            status_code=status,
            headers={"HX-Retarget": "#feedback", "HX-Reswap": "innerHTML"},
        )

    def remember(self, offers: list[Reference]) -> None:
        with self.names_lock:
            self.names.update((offer.id, offer.name) for offer in offers)

    def named_stream(
        self, request: Request, stream: StreamView, message: str | None = None
    ) -> Response:
        with self.names_lock:
            names = self.names.copy()
        return self.render(request, "stream.html", stream=stream, names=names, message=message)

    def load_workspace(self, campaign_id: int) -> tuple[CampaignView, dict[int, str]]:
        view = self.editor.sync(campaign_id)
        if any(stream.schema_ == "landings" for stream in view.streams):
            with suppress(AppError):
                self.remember(self.campaigns.offer_catalog())
        with self.names_lock:
            return view, self.names.copy()

    def mount(self, app: FastAPI) -> None:
        app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
        routes = app.router

        @routes.get("/favicon.ico", include_in_schema=False)
        def favicon() -> Response:
            return Response(status_code=204)

        @routes.get("/", include_in_schema=False)
        def home(request: Request, campaign_id: PositiveId | None = None) -> Response:
            view: CampaignView | None = None
            names: dict[int, str] = {}
            message = None
            status = 200
            if campaign_id is not None:
                try:
                    view, names = self.load_workspace(campaign_id)
                except AppError as error:
                    message = str(error)
                    status = error.status
            response = self.render(
                request, "editor.html", campaign_id=campaign_id,
                view=view, names=names, message=message,
            )
            response.status_code = status
            return response

        @routes.get("/new", include_in_schema=False)
        def new(request: Request) -> Response:
            return self.render(
                request, "editor.html", create_open=True
            )

        @routes.get("/ui/lookups", include_in_schema=False)
        def lookups(request: Request) -> Response:
            return self.render(request, "lookups.html", options=self.campaigns.lookups())

        @routes.post("/ui/campaigns", include_in_schema=False)
        def create(request: Request, data: Annotated[CreateCampaign, Form()]) -> Response:
            campaign = self.campaigns.create(data)
            response = self.render(
                request, "notice.html", message=f"Кампания «{campaign.name}» создана.", tone="ok"
            )
            response.headers["HX-Redirect"] = f"/?campaign_id={campaign.id}"
            return response

        @routes.post("/ui/sync", include_in_schema=False)
        def sync(request: Request, campaign_id: Annotated[PositiveId, Form()]) -> Response:
            view, names = self.load_workspace(campaign_id)
            response = self.render(
                request, "workspace.html", view=view, names=names
            )
            response.headers["HX-Push-Url"] = f"/?campaign_id={campaign_id}"
            return response

        @routes.post("/ui/streams/{stream_id}/edit", include_in_schema=False)
        def edit(
            request: Request, stream_id: PositiveId, data: Annotated[Edit, Form()]
        ) -> Response:
            return self.named_stream(request, self.editor.edit(stream_id, data))

        @routes.post("/ui/streams/{stream_id}/cancel", include_in_schema=False)
        def cancel(
            request: Request, stream_id: PositiveId, data: Annotated[Revision, Form()]
        ) -> Response:
            return self.named_stream(
                request, self.editor.cancel(stream_id, data), "Черновик отменён."
            )

        @routes.post("/ui/streams/{stream_id}/publish", include_in_schema=False)
        def publish(
            request: Request, stream_id: PositiveId, data: Annotated[Revision, Form()]
        ) -> Response:
            return self.named_stream(
                request, self.editor.publish(stream_id, data), "Изменения сохранены в Keitaro."
            )
