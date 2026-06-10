from fastapi import FastAPI

from api.debug_route import router as debug_router
from api.websockets_route import router as websocket_router

app = FastAPI()

app.include_router(debug_router)
app.include_router(websocket_router)