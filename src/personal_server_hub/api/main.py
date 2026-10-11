from fastapi import FastAPI
from personal_server_hub.api.routers import game_accounts, health, help

app = FastAPI()
app.include_router(health.router)
app.include_router(help.router)
app.include_router(game_accounts.router)