from fastapi import FastAPI

from api.routers import health

app = FastAPI(title="gallery-dl-webui")
app.include_router(health.router)
