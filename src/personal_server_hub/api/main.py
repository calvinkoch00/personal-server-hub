from fastapi import Depends, FastAPI
from personal_server_hub.api.dependencies import get_principal
from personal_server_hub.api.routers import billing, dns, game_accounts, help, servers, users, whitelist

# Every route requires an authenticated principal. Routes that need more
# (registered user, admin) add require_registered / require_admin on top.
app = FastAPI(dependencies=[Depends(get_principal)])
app.include_router(dns.router)
app.include_router(help.router)
app.include_router(game_accounts.router)
app.include_router(users.router)
app.include_router(billing.router)
app.include_router(whitelist.router)
app.include_router(servers.router)