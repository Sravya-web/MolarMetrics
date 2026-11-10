"""MolarMetrics web API.

Start (from the project folder, with the virtual environment active):

    python -m molarmetrics.api            # http://127.0.0.1:8000

(``create_app`` is a factory: ``uvicorn molarmetrics.api.app:create_app --factory``.)

Security model (local, single-user): binds to this computer only; a random
session cookie (HttpOnly, SameSite=Strict) owns datasets; every dataset and
upload lookup checks ownership (unknown or foreign IDs get 404); requests
must target localhost (DNS-rebinding protection); state-changing requests
need the ``X-MolarMetrics`` header (cross-site forms cannot send it).
Logs carry request IDs, routes, status codes and timings only.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from molarmetrics.agent.tools import TOOL_SPECS, run_analysis
from molarmetrics.analytics.db import connect_readonly
from molarmetrics.analytics.export import csv_filename, result_csv_bytes
from molarmetrics.analytics.params import arg_models_for
from molarmetrics.api import overview as overview_mod
from molarmetrics.api.ask_service import (
    UNAVAILABLE_MESSAGE,
    AskFailed,
    AskService,
    Busy,
    InvalidQuestion,
    QuestionsUnavailable,
    suggested_questions,
)
from molarmetrics.api.presenters import KIND_TO_TOOL, PUBLIC_FILTERS, display_title
from molarmetrics.api.retention import Retention
from molarmetrics.api.schemas import (
    ActivateRequest,
    AskRequest,
    AskResponse,
    Coverage,
    DatasetMeta,
    DatasetRef,
    Limits,
    OverviewPayload,
    SessionState,
    Suggestions,
    UploadBatchOut,
)
from molarmetrics.api.settings import WebSettings, get_web_settings
from molarmetrics.api.store import DatasetRow, Store
from molarmetrics.api.uploads import NotReady, UploadError, UploadService
from molarmetrics.config import PROJECT_ROOT, get_settings
from molarmetrics.dataset import SAMPLE_CONTEXT, DatasetContext, context_from_db
from molarmetrics.ingest.build import ImportFailed
from molarmetrics.ingest.fields import RECORD_SPECS
from molarmetrics.ingest.templates import example_bundle_zip, record_type_catalog, template_csv, templates_zip
from molarmetrics.ingest.validate import ImportConfig, ValidationReport

log = logging.getLogger("molarmetrics.api")
COOKIE = "mm_session"
CSRF_HEADER = "x-molarmetrics"
WEB_DIST = PROJECT_ROOT / "web" / "dist"
_SPECS = {name: (model, fn) for name, model, fn, _ in TOOL_SPECS}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


@dataclass
class Handle:
    """An owned, unexpired dataset ready to query."""

    row: DatasetRow
    ctx: DatasetContext
    db_path: Path

    @property
    def ref(self) -> DatasetRef:
        return DatasetRef(id=self.row.id, name=self.row.name, kind=self.row.kind)


class AppState:
    def __init__(self, settings: WebSettings, ask: AskService):
        self.settings = settings
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        settings.runtime_dir.chmod(0o700)  # private to this user account
        self.store = Store(settings.registry_path)
        self.ask = ask
        self._contexts: dict[str, DatasetContext] = {}
        self.retention = Retention(self.store, settings, on_dataset_removed=self._forget)
        self.uploads = UploadService(self.store, settings, self.retention)
        self._sample_counts: dict[str, int] | None = None

    def _forget(self, dataset_id: str) -> None:
        self._contexts.pop(dataset_id, None)
        self.ask.forget_dataset(dataset_id)

    # --- sessions ---------------------------------------------------------------------
    def session(self, request: Request, response: Response) -> str:
        token = request.cookies.get(COOKIE)
        session_id = hashlib.sha256(token.encode()).hexdigest() if token else None
        row = self.store.get_session(session_id) if session_id else None
        if row is not None and self.retention.expired(row["last_seen"]):
            for ds in self.store.list_datasets(session_id):
                self.retention.remove_dataset(ds)
            self.store.delete_session(session_id)
            row = None
        if row is None:
            token = secrets.token_urlsafe(32)
            session_id = hashlib.sha256(token.encode()).hexdigest()
            self.store.create_session(session_id)
        else:
            self.store.touch_session(session_id)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/",
                            max_age=int(self.settings.retention_seconds))
        return session_id

    # --- datasets ------------------------------------------------------------------------
    def owned(self, session_id: str, dataset_id: str) -> DatasetRow:
        row = self.store.get_dataset(dataset_id)
        if row is None or row.session_id != session_id:
            raise ApiError(404, "dataset_not_found", "This dataset isn't available. It may have been removed.")
        if row.kind == "uploaded" and self.retention.expired(row.last_used_at):
            self.retention.remove_dataset(row)
            raise ApiError(410, "dataset_expired", "This dataset has expired and was deleted. Upload it again "
                                                   "to continue.")
        return row

    def handle(self, session_id: str, dataset_id: str) -> Handle:
        row = self.owned(session_id, dataset_id)
        self.store.touch_dataset(row.id)
        if row.kind == "sample":
            path = get_settings().db_path
            if not path.exists():
                raise ApiError(503, "sample_missing", "The sample data isn't available on this computer.")
            return Handle(row, SAMPLE_CONTEXT, path)
        path = Path(row.db_path)
        ctx = self._contexts.get(row.id)
        if ctx is None:
            conn = connect_readonly(path)
            try:
                ctx = context_from_db(conn, name=row.name)
            finally:
                conn.close()
            self._contexts[row.id] = ctx
        return Handle(row, ctx, path)

    def sample_counts(self) -> dict[str, int]:
        if self._sample_counts is None:
            conn = connect_readonly(get_settings().db_path)
            try:
                self._sample_counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                       for t in ("appointments", "treatments", "payments", "patients", "dentists")}
            finally:
                conn.close()
        return self._sample_counts

    def meta(self, row: DatasetRow, active_id: str | None) -> DatasetMeta:
        if row.kind == "sample":
            s, e = SAMPLE_CONTEXT.coverage_start, SAMPLE_CONTEXT.coverage_end
            caps, counts, notes, expires = sorted(SAMPLE_CONTEXT.capabilities), self.sample_counts(), [], None
        else:
            m = row.meta
            s, e, caps, counts, notes = (m["coverage_start"], m["coverage_end"], m["capabilities"], m["counts"],
                                         m["import_notes"])
            expires = _iso(self.retention.expires_at(row.last_used_at))
        return DatasetMeta(id=row.id, name=row.name, kind=row.kind,
                           coverage=Coverage(start=s, end=e, label=overview_mod.coverage_label(s, e)),
                           capabilities=caps, counts=counts, import_notes=notes, created_at=_iso(row.created_at),
                           last_used_at=_iso(row.last_used_at), expires_at=expires, active=row.id == active_id)

    def session_state(self, session_id: str) -> SessionState:
        session = self.store.get_session(session_id)
        active = session["active_dataset_id"] if session else None
        rows = []
        for row in self.store.list_datasets(session_id):
            if row.kind == "uploaded" and self.retention.expired(row.last_used_at):
                self.retention.remove_dataset(row)
                continue
            rows.append(row)
        if active and active not in {r.id for r in rows}:
            active = None
        return SessionState(datasets=[self.meta(r, active) for r in rows], active_dataset_id=active,
                            questions_available=self.ask.questions_available(),
                            retention_hours=self.settings.retention_hours,
                            limits=Limits(max_file_mb=self.settings.max_file_mb, max_files=self.settings.max_files))


def create_app(settings: WebSettings | None = None, ask_service: AskService | None = None) -> FastAPI:
    settings = settings or get_web_settings()
    state = AppState(settings, ask_service or AskService())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await run_in_threadpool(state.retention.sweep, None, True)  # startup: expired items only
        task = asyncio.create_task(_sweeper())
        try:
            yield
        finally:
            task.cancel()

    async def _sweeper():
        while True:
            await asyncio.sleep(settings.sweep_minutes * 60)
            try:
                await run_in_threadpool(state.retention.sweep)
            except Exception as exc:  # never let the sweeper die
                log.warning("Retention sweep failed (%s)", type(exc).__name__)

    app = FastAPI(title="MolarMetrics", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.mm = state

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        is_api = request.url.path.startswith("/api/")
        if is_api and request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
            response = _error(403, "forbidden", "This request isn't allowed.")
        elif is_api and request.url.path == "/api/uploads" and request.method == "POST" and not _size_ok(request):
            response = _error(413, "upload_too_large", f"Uploads can be up to {settings.max_files} files of "
                                                       f"{settings.max_file_mb} MB each.")
        else:
            response = await call_next(request)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        route = getattr(request.scope.get("route"), "path", "static" if not is_api else "unmatched")
        log.info("request=%s %s %s status=%s ms=%.0f", request_id, request.method, route, response.status_code,
                 (time.perf_counter() - started) * 1000)
        return response

    def _size_ok(request: Request) -> bool:
        length = request.headers.get("content-length")
        limit = settings.max_files * settings.max_file_bytes + 1024 * 1024
        return length is not None and length.isdigit() and int(length) <= limit

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        message = "Not found." if exc.status_code == 404 else "This request couldn't be completed."
        return _error(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, _exc: RequestValidationError):
        return _error(422, "invalid_request", "Something in the request wasn't valid. Please try again.")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.error("request=%s failed (%s)", getattr(request.state, "request_id", "-"), type(exc).__name__)
        return _error(500, "server_error", "Something went wrong. Please try again.")

    api = APIRouter(prefix="/api")

    def session_id(request: Request, response: Response) -> str:
        return state.session(request, response)

    # --- session & datasets ------------------------------------------------------------
    @api.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @api.get("/session", response_model=SessionState)
    def get_session(sid: str = Depends(session_id)):
        return state.session_state(sid)

    @api.put("/session/active", response_model=SessionState)
    def activate(body: ActivateRequest, sid: str = Depends(session_id)):
        row = state.owned(sid, body.dataset_id)
        state.store.set_active(sid, row.id)
        state.store.touch_dataset(row.id)
        state.ask.clear_session(sid)  # switching clears conversational context
        return state.session_state(sid)

    @api.post("/datasets/sample", response_model=DatasetMeta)
    def activate_sample(sid: str = Depends(session_id)):
        """Explicitly add the bundled sample data to this session and make it active."""
        if not get_settings().db_path.exists():
            raise ApiError(503, "sample_missing", "The sample data isn't available on this computer.")
        existing = next((r for r in state.store.list_datasets(sid) if r.kind == "sample"), None)
        if existing is None:
            now = time.time()
            existing = DatasetRow(id=uuid.uuid4().hex, session_id=sid, kind="sample", name="Sample clinic",
                                  db_path="sample", created_at=now, last_used_at=now, meta={})
            state.store.add_dataset(existing, activate=True)
        else:
            state.store.set_active(sid, existing.id)
            state.store.touch_dataset(existing.id)
        state.ask.clear_session(sid)
        return state.meta(state.store.get_dataset(existing.id), existing.id)

    @api.get("/datasets/{dataset_id}", response_model=DatasetMeta)
    def get_dataset(dataset_id: str, sid: str = Depends(session_id)):
        row = state.owned(sid, dataset_id)
        session = state.store.get_session(sid)
        return state.meta(row, session["active_dataset_id"] if session else None)

    @api.delete("/datasets/{dataset_id}", response_model=SessionState)
    def remove_dataset(dataset_id: str, sid: str = Depends(session_id)):
        row = state.owned(sid, dataset_id)
        state.retention.remove_dataset(row)  # deletes files, verifies, then the registry row
        state.ask.clear_session(sid)
        return state.session_state(sid)

    @api.get("/datasets/{dataset_id}/overview", response_model=OverviewPayload)
    def get_overview(dataset_id: str, start: str | None = None, end: str | None = None,
                     sid: str = Depends(session_id)):
        h = state.handle(sid, dataset_id)
        conn = connect_readonly(h.db_path)
        try:
            return overview_mod.build_overview(conn, h.ctx, h.ref, start, end)
        except overview_mod.PeriodError as exc:
            raise ApiError(422, "invalid_period", str(exc)) from None
        except sqlite3.Error:
            raise ApiError(500, "data_unreadable", "The data for this dataset couldn't be read.") from None
        finally:
            conn.close()

    @api.get("/datasets/{dataset_id}/suggestions", response_model=Suggestions)
    def get_suggestions(dataset_id: str, sid: str = Depends(session_id)):
        h = state.handle(sid, dataset_id)
        return Suggestions(dataset=h.ref, questions=suggested_questions(h.ctx))

    @api.post("/datasets/{dataset_id}/ask", response_model=AskResponse)
    def ask(dataset_id: str, body: AskRequest, request: Request, sid: str = Depends(session_id)):
        h = state.handle(sid, dataset_id)
        try:
            return state.ask.ask(sid, h.ref, h.db_path, h.ctx, body.question, request.state.request_id)
        except InvalidQuestion as exc:
            raise ApiError(422, "invalid_question", str(exc)) from None
        except Busy:
            raise ApiError(409, "busy", "MolarMetrics is still answering your previous question.") from None
        except QuestionsUnavailable:
            raise ApiError(503, "questions_unavailable", UNAVAILABLE_MESSAGE) from None
        except AskFailed as exc:
            if exc.kind == "timeout":
                raise ApiError(504, "timeout", "That took too long to answer. Please try again.") from None
            raise ApiError(502, "answer_failed", "Something went wrong while answering. Please try again.") from None

    @api.get("/datasets/{dataset_id}/export.csv")
    def export(dataset_id: str, request: Request, analysis: str = Query(...), sid: str = Depends(session_id)):
        h = state.handle(sid, dataset_id)
        tool = KIND_TO_TOOL.get(analysis)
        if tool is None:
            raise ApiError(400, "invalid_request", "This download isn't available.")
        args: dict = {}
        for key in PUBLIC_FILTERS:
            values = request.query_params.getlist(key)
            if values:
                args[key] = values if key == "procedures" else values[0]
        if analysis == "outstanding":
            args["metric"] = "outstanding_balance"
        result = run_analysis(tool, arg_models_for(h.ctx)[tool], _SPECS[tool][1], args, h.db_path, h.ctx)
        if result.status in ("error", "unavailable"):
            raise ApiError(422, "not_exportable", "This result can't be downloaded for this dataset.")
        body = b"\xef\xbb\xbf" + result_csv_bytes(result, dataset_label=h.row.name)  # BOM: Excel reads UTF-8
        name = csv_filename(result, dataset_label=h.row.name, title=display_title(result, analysis))
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # --- templates ------------------------------------------------------------------------
    @api.get("/record-types")
    def record_types() -> list[dict]:
        return record_type_catalog()

    def _download(data: bytes, filename: str, media_type: str) -> Response:
        return Response(data, media_type=media_type,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @api.get("/templates/all.zip")
    def all_templates():
        return _download(templates_zip(), "molarmetrics-templates.zip", "application/zip")

    @api.get("/templates/example-bundle.zip")
    def example_bundle():
        return _download(example_bundle_zip(), "molarmetrics-example-sunrise-dental.zip", "application/zip")

    @api.get("/templates/{record_type}.csv")
    def one_template(record_type: str):
        if record_type not in RECORD_SPECS:
            raise ApiError(404, "not_found", "There's no template with that name.")
        return _download(template_csv(record_type), f"{record_type}.csv", "text/csv; charset=utf-8")

    # --- uploads --------------------------------------------------------------------------
    def owned_batch(sid: str, batch_id: str):
        batch = state.store.get_batch(batch_id)
        if batch is None or batch.session_id != sid:
            raise ApiError(404, "upload_not_found", "This upload isn't available any more. Please upload the "
                                                    "files again.")
        if state.retention.expired(batch.last_used_at):
            state.uploads.cancel(batch)
            raise ApiError(410, "upload_expired", "This upload has expired. Please upload the files again.")
        return batch

    @api.post("/uploads", response_model=UploadBatchOut)
    async def upload(request: Request, response: Response):
        sid = state.session(request, response)
        form = await request.form(max_files=settings.max_files + 1, max_fields=20)
        try:
            files = []
            for item in form.getlist("files"):
                if hasattr(item, "read"):
                    data = await item.read(settings.max_file_bytes + 1)
                    files.append((item.filename or "", data))
        finally:
            await form.close()
        try:
            return await run_in_threadpool(state.uploads.create, sid, files)
        except UploadError as exc:
            raise ApiError(422, "upload_rejected", "Some files couldn't be read.",
                           files=[r.model_dump() for r in exc.rejections]) from None

    @api.get("/uploads/{batch_id}", response_model=UploadBatchOut)
    def get_upload(batch_id: str, sid: str = Depends(session_id)):
        batch = owned_batch(sid, batch_id)
        state.store.update_batch(batch.id)
        return state.uploads.describe(batch)

    @api.post("/uploads/{batch_id}/validate", response_model=ValidationReport)
    def validate(batch_id: str, config: ImportConfig, sid: str = Depends(session_id)):
        return state.uploads.validate(owned_batch(sid, batch_id), config)

    @api.delete("/uploads/{batch_id}/files/{file_id}", response_model=UploadBatchOut)
    def remove_file(batch_id: str, file_id: str, sid: str = Depends(session_id)):
        out = state.uploads.remove_file(owned_batch(sid, batch_id), file_id)
        if out is None:
            raise ApiError(404, "file_not_found", "That file isn't part of this upload.")
        return out

    @api.get("/uploads/{batch_id}/issues.csv")
    def issues_csv(batch_id: str, sid: str = Depends(session_id)):
        data = b"\xef\xbb\xbf" + state.uploads.issues_csv(owned_batch(sid, batch_id))
        return _download(data, "molarmetrics-import-issues.csv", "text/csv; charset=utf-8")

    @api.post("/uploads/{batch_id}/import", response_model=DatasetMeta)
    def import_upload(batch_id: str, config: ImportConfig, sid: str = Depends(session_id)):
        batch = owned_batch(sid, batch_id)
        try:
            row = state.uploads.import_batch(batch, config, sid)
        except NotReady as exc:
            raise ApiError(422, "not_ready", exc.report.summary,
                           report=exc.report.model_dump(mode="json")) from None
        except (ImportFailed, OSError, sqlite3.Error) as exc:
            log.error("Import failed (%s)", type(exc).__name__)
            raise ApiError(500, "import_failed", "The import couldn't be completed. Your current data is "
                                                 "unchanged.") from None
        state.ask.clear_session(sid)
        return state.meta(row, row.id)

    @api.delete("/uploads/{batch_id}", status_code=204)
    def cancel_upload(batch_id: str, sid: str = Depends(session_id)):
        state.uploads.cancel(owned_batch(sid, batch_id))
        return Response(status_code=204)

    app.include_router(api)

    # --- the built frontend (production mode) -------------------------------------------------
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/") or path == "api":
            raise ApiError(404, "not_found", "Not found.")
        if not (WEB_DIST / "index.html").exists():
            return _error(404, "frontend_not_built", "The web app hasn't been built. Run scripts/start.sh, or "
                                                     "use the development server.")
        root = WEB_DIST.resolve()
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        response = FileResponse(root / "index.html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app

