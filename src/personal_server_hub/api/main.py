from fastapi import FastAPI
from personal_server_hub.api.routers import health

app = FastAPI()
app.include_router(health.router)