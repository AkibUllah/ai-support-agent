"""FastAPI app: demo login, chat sessions with traces, admin views, static chat UI."""

from __future__ import annotations

import hmac
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from support_agent import __version__
from support_agent.api.schemas import (
    CustomerOut,
    HealthOut,
    MessageIn,
    SessionCreate,
    SessionCreated,
    SessionOut,
    TurnHistory,
    TurnOut,
)
from support_agent.config import Settings, get_settings
from support_agent.logging_config import configure_logging
from support_agent.service import AuthError, SupportService

log = logging.getLogger("support_agent.api")


def _customer_out(c: dict[str, Any]) -> CustomerOut:
    phone = c["phone"]
    return CustomerOut(
        id=c["id"],
        name=c["name"],
        district=c["district"],
        phone_masked=f"{phone[:3]}*****{phone[-3:]}",
    )


def create_app(settings: Settings | None = None, service: SupportService | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = service or SupportService(settings)
        yield

    app = FastAPI(
        title="AI Support Agent",
        version=__version__,
        description=(
            "Customer-support agent for Haat Online (a fictional Bangladeshi shop). The model "
            "proposes tool calls; authorisation, argument validation, the refund/address policy "
            "and prompt-injection screening are enforced in code. Every turn returns a trace."
        ),
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_log(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info(
            "%s %s %s %.1fms id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
            rid,
        )
        return response

    def svc(request: Request) -> SupportService:
        return request.app.state.service

    def session_auth(
        session_id: str, request: Request, authorization: str = Header(default="")
    ) -> dict[str, Any]:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        try:
            return svc(request).authenticate(session_id, token)
        except AuthError as exc:
            raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc

    def admin_auth(x_admin_key: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_admin_key, settings.admin_api_key):
            raise HTTPException(403, "admin key required")

    @app.get("/api/health", response_model=HealthOut, tags=["meta"])
    def health(request: Request) -> HealthOut:
        return HealthOut(
            status="ok",
            version=__version__,
            llm_provider=settings.llm_provider,
            tools=svc(request).tools.names,
        )

    @app.get("/api/tools", tags=["meta"])
    def tools(request: Request) -> list[dict[str, Any]]:
        """JSON schemas of the tools offered to the model."""
        return svc(request).tools.schemas()

    @app.get("/api/customers", response_model=list[CustomerOut], tags=["sessions"])
    def customers(request: Request) -> list[CustomerOut]:
        """Seeded demo customers (stands in for a real login)."""
        return [_customer_out(c) for c in svc(request).repo.list_customers()]

    @app.post("/api/sessions", response_model=SessionCreated, status_code=201, tags=["sessions"])
    def create_session(body: SessionCreate, request: Request) -> SessionCreated:
        try:
            new = svc(request).start_session(body.customer_id)
        except LookupError as exc:
            raise HTTPException(404, "unknown customer") from exc
        return SessionCreated(
            session_id=new.session_id,
            token=new.token,
            customer=_customer_out(new.customer),
            state="active",
        )

    @app.get("/api/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
    def get_session(
        request: Request, session: dict[str, Any] = Depends(session_auth)
    ) -> SessionOut:
        service = svc(request)
        customer = service.repo.get_customer(session["customer_id"])
        turns = [
            TurnHistory(
                turn_id=t["id"],
                user=t["user_text"],
                reply=t["reply"],
                trace=t["trace"],
                created_at=t["created_at"],
            )
            for t in service.repo.list_turns(session["id"])
        ]
        return SessionOut(
            session_id=session["id"],
            customer=_customer_out(customer),  # type: ignore[arg-type]
            state=session["state"],
            handoff_reason=session["handoff_reason"],
            turns=turns,
        )

    @app.post("/api/sessions/{session_id}/messages", response_model=TurnOut, tags=["sessions"])
    def send_message(
        body: MessageIn, request: Request, session: dict[str, Any] = Depends(session_auth)
    ) -> TurnOut:
        if len(body.text) > settings.max_message_chars:
            raise HTTPException(413, f"message longer than {settings.max_message_chars} characters")
        result = svc(request).send(session, body.text)
        return TurnOut(
            turn_id=result.turn_id, reply=result.reply, state=result.state, trace=result.trace
        )

    @app.get("/api/admin/handoffs", tags=["admin"], dependencies=[Depends(admin_auth)])
    def handoffs(request: Request) -> dict[str, Any]:
        """Sessions waiting for a human, plus open tickets and recent security events."""
        repo = svc(request).repo
        return {
            "sessions": repo.sessions_in_state("handoff"),
            "tickets": repo.list_tickets(),
            "security_events": repo.audit_events()[-50:],
        }

    ui = settings.ui_dir
    if ui.is_dir() and (ui / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=ui / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (ui / path).resolve()
            if path and candidate.is_file() and ui.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(ui / "index.html")

    return app


app = create_app()
