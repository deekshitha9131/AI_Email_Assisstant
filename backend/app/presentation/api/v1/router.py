from fastapi import APIRouter

from app.presentation.api.v1.routers import (
	ai,
	auth,
	compose_drafts,
	drafts,
	emails,
	gmail,
	health,
	status,
	threads,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(gmail.router)
api_router.include_router(emails.router)
api_router.include_router(status.router)
api_router.include_router(threads.router)
api_router.include_router(ai.router)
api_router.include_router(drafts.router)
api_router.include_router(compose_drafts.router)
