from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import Base, engine
from dependencies import verify_access_token
from routes import (
    auth_routes, currency_routes, kodelambung_routes,customer_routes, item_routes, vendor_routes,
    category_routes,utils_routes,sumberdana_routes, pembayaran_routes,pengembalian_routes,satuan_routes,user_routes, warehouse_routes,upload_routes, termofpayment_routes, pembelian_routes, penjualan_routes
)
from fastapi.staticfiles import StaticFiles
import os


load_dotenv()

# app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app = FastAPI()

from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer

security_scheme = HTTPBearer()

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="My API",
        version="1.0.0",
        description="FastAPI project with JWT Auth",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    for path in openapi_schema["paths"]:
        for method in openapi_schema["paths"][path]:
            if "security" not in openapi_schema["paths"][path][method]:
                openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created")
    print("🚀 Starting FastAPI project")

origins = [
    "http://localhost:3000",
    "https://qiu-system.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Public routes


print("STATIC_URL =", os.getenv("STATIC_URL"))  # You should see the full absolute path

os.makedirs("uploads/items", exist_ok=True)  
app.mount("/static", StaticFiles(directory=os.getenv("STATIC_URL")), name="static")


# app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
# app.include_router(utils_routes.router, prefix="/utils", tags=["Utils"], dependencies=[Depends(verify_access_token)])
# app.include_router(satuan_routes.router, prefix="/satuan", tags=["Satuan"], dependencies=[Depends(verify_access_token)])
# app.include_router(termofpayment_routes.router, prefix="/top", tags=["Term of Payment"], dependencies=[Depends(verify_access_token)])
# app.include_router(warehouse_routes.router, prefix="/warehouse", tags=["Warehouse"], dependencies=[Depends(verify_access_token)])
# app.include_router(category_routes.router, prefix="/category", tags=["Category"], dependencies=[Depends(verify_access_token)])
# app.include_router(vendor_routes.router, prefix="/vendor", tags=["Vendor"], dependencies=[Depends(verify_access_token)])
# app.include_router(sumberdana_routes.router, prefix="/sumberdana", tags=["Sumber Dana"], dependencies=[Depends(verify_access_token)])
# app.include_router(currency_routes.router, prefix="/currency", tags=["Currency"], dependencies=[Depends(verify_access_token)])
# app.include_router(customer_routes.router, prefix="/customer", tags=["Customer"], dependencies=[Depends(verify_access_token)])
# app.include_router(item_routes.router, prefix="/item", tags=["Item"], dependencies=[Depends(verify_access_token)])
# app.include_router(pembelian_routes.router, prefix="/pembelian", tags=["Pembelian"], dependencies=[Depends(verify_access_token)])
# app.include_router(penjualan_routes.router, prefix="/penjualan", tags=["Penjualan"], dependencies=[Depends(verify_access_token)])
# app.include_router(pembayaran_routes.router, prefix="/pembayaran", tags=["Pembayaran"], dependencies=[Depends(verify_access_token)])
# app.include_router(pengembalian_routes.router, prefix="/pengembalian", tags=["Pengembalian"], dependencies=[Depends(verify_access_token)])
# app.include_router(user_routes.router, prefix="/users", tags=["Penjualan"], dependencies=[Depends(verify_access_token)])
# app.include_router(upload_routes.router, prefix="/upload", tags=["Upload"])

app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
app.include_router(utils_routes.router, prefix="/utils", tags=["Utils"])
app.include_router(satuan_routes.router, prefix="/satuan", tags=["Satuan"])
app.include_router(sumberdana_routes.router, prefix="/sumberdana", tags=["Sumber Dana"])
app.include_router(termofpayment_routes.router, prefix="/top", tags=["Term of Payment"])
app.include_router(warehouse_routes.router, prefix="/warehouse", tags=["Warehouse"])
app.include_router(category_routes.router, prefix="/category", tags=["Category"])
app.include_router(vendor_routes.router, prefix="/vendor", tags=["Vendor"])
app.include_router(currency_routes.router, prefix="/currency", tags=["Currency"])
app.include_router(customer_routes.router, prefix="/customer", tags=["Customer"])
app.include_router(item_routes.router, prefix="/item", tags=["Item"])
app.include_router(pembelian_routes.router, prefix="/pembelian", tags=["Pembelian"])
app.include_router(penjualan_routes.router, prefix="/penjualan", tags=["Penjualan"])
app.include_router(pembayaran_routes.router, prefix="/pembayaran", tags=["Pembayaran"])
app.include_router(pengembalian_routes.router, prefix="/pengembalian", tags=["Pengembalian"])
app.include_router(kodelambung_routes.router, prefix="/kodelambung", tags=["Kode Lambung"])
app.include_router(user_routes.router, prefix="/users", tags=["Users"])
app.include_router(upload_routes.router, prefix="/upload", tags=["Upload"])

