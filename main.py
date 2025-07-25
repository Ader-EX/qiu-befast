import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import Base, engine
from routes import auth_routes

# Load env (e.g., .env.office or .env.home)
load_dotenv()



# Create database tables


# Init FastAPI app
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    print("Starting project")

# Setup CORS (customize if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO :NEED TO UPDATE FOR PROD
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




# Include routers
app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])


@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI App"}
