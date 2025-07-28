import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import Base, engine
from routes import auth_routes,currency_routes, item_routes,vendor_routes,category_routes, satuan_routes,warehouse_routes, termofpayment_routes


# Load env (e.g., .env or .env.home)
load_dotenv()


# Init FastAPI app
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created.")
    print("🚀 Starting FastAPI project")

# Setup CORS (customize if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["localhost:3000","https://qiu-system.vercel.app"],  # TODO :NEED TO UPDATE FOR PROD
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




# Include routers
app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
app.include_router(satuan_routes.router, prefix="/satuan", tags=["Satuan"])
app.include_router(termofpayment_routes.router, prefix="/top", tags=["Term of Payment"])
app.include_router(warehouse_routes.router, prefix="/warehouse", tags=["Warehouse"])
app.include_router(category_routes.router, prefix="/category", tags=["Category"])
app.include_router(vendor_routes.router, prefix="/vendor", tags=["Vendor"])
app.include_router(currency_routes.router, prefix="/currency", tags=["Currency"])

app.include_router(item_routes.router, prefix="/item", tags=["Item"])

@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI App"}



@app.get("/iseng")
async def iseng():
    return {"message": "Welcome to FastAPI App"}
