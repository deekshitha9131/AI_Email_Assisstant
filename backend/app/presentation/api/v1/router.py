from fastapi import APIRouter

from app.presentation.api.v1.routers import (
	ai,
	auth,
	automation,
	compose_drafts,
	drafts,
	emails,
	follow_ups,
    gmail,
    health,
    notifications,
	status,
	threads,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(automation.router)
api_router.include_router(gmail.router)
api_router.include_router(emails.router)
api_router.include_router(follow_ups.router)
api_router.include_router(notifications.router)
api_router.include_router(status.router)
api_router.include_router(threads.router)
api_router.include_router(ai.router)
api_router.include_router(drafts.router)
api_router.include_router(compose_drafts.router)
