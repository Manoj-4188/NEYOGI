"""Aggregate router for API v1."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import auth, forecast, map, officer, parcel, prices, webhooks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(map.router)
api_router.include_router(forecast.router)
api_router.include_router(prices.router)
api_router.include_router(parcel.router)
api_router.include_router(officer.router)
api_router.include_router(webhooks.router)
