"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .db import SessionLocal, init_db
from .engine import FieldError
from .routers import audits, decisions, rules
from .seed import seed_rules

templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))


def _field_errors_from_request_validation(exc: RequestValidationError) -> list[dict[str, str]]:
    errors = []
    for err in exc.errors():
        loc = [p for p in err.get("loc", []) if p not in ("body",)]
        field = ".".join(str(p) for p in loc) or "body"
        errors.append({"field": field, "message": err.get("msg", "参数不合法")})
    return errors


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        init_db()
        db = SessionLocal()
        try:
            seed_rules(db)
        finally:
            db.close()
        yield

    app = FastAPI(
        title=config.APP_NAME,
        version="1.0.0",
        description="回收分拣来料污染判定：可版本化接收规则、结论固化、审计与导出。",
        lifespan=lifespan,
    )

    @app.exception_handler(FieldError)
    async def _field_error_handler(request: Request, exc: FieldError):  # noqa: ARG001
        return JSONResponse(status_code=422,
                            content={"error": "field_validation_failed", "errors": exc.errors})

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(request: Request, exc: RequestValidationError):  # noqa: ARG001
        return JSONResponse(
            status_code=422,
            content={"error": "request_validation_failed",
                     "errors": _field_errors_from_request_validation(exc)},
        )

    app.include_router(decisions.router)
    app.include_router(rules.router)
    app.include_router(audits.router)

    app.mount("/static",
              StaticFiles(directory=str(config.BASE_DIR / "app" / "static")),
              name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request,
                                                         "app_name": config.APP_NAME})

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "env": config.APP_ENV}

    return app


app = create_app()
