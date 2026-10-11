from fastapi import FastAPI
from personal_server_hub.api.routers import health, help

app = FastAPI()
app.include_router(health.router)
app.include_router(help.router)