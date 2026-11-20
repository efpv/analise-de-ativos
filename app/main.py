from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

app = FastAPI(
    title="Preço Justo Bazin",
    description="Cálculo de valuation de ações da B3 pelo Método de Bazin",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
