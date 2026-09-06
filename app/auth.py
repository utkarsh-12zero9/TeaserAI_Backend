from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta, timezone
import os
import bcrypt
import jwt
import certifi
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

load_dotenv()

# Router Setup
router = APIRouter(prefix="/auth", tags=["auth"])

# Security and Constants
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "teaserai-super-secret-teaser-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

security = HTTPBearer()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "teaserai")

# Initialize MongoDB Client with certifi CA bundle for secure SSL/TLS connection
client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
db = client[MONGODB_DB_NAME]
users_collection = db["users"]

# Initialize MongoDB Unique index
@router.on_event("startup")
async def init_db():
    try:
        await users_collection.create_index("email", unique=True)
    except Exception as e:
        print(f"Error creating unique index on email: {e}")


# Schema definitions
class UserRegisterSchema(BaseModel):
    email: EmailStr
    password: str

class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str

# Password hashing helpers
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

# JWT Helpers
def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Dependency to fetch the current user
async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    token = credentials.credentials
    payload = verify_token(token)
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return email

# Auth Routes
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegisterSchema):
    email = user_data.email.lower()
    hashed_pwd = hash_password(user_data.password)

    try:
        # Check if user already exists
        existing_user = await users_collection.find_one({"email": email})
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered"
            )
        
        # Insert user with explicit user_id
        import uuid
        user_id = str(uuid.uuid4())
        user_doc = {
            "user_id": user_id,
            "email": email,
            "hashed_password": hashed_pwd,
            "created_at": datetime.now(timezone.utc)
        }
        await users_collection.insert_one(user_doc)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during registration: {str(e)}"
        )

    return {"message": "User registered successfully", "user_id": user_id}

@router.post("/login", response_model=TokenSchema)
async def login(user_data: UserLoginSchema):
    email = user_data.email.lower()
    
    try:
        user = await users_collection.find_one({"email": email})
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during login: {str(e)}"
        )

    if not user or not verify_password(user_data.password, user.get("hashed_password")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Ensure user has a user_id
    user_id = user.get("user_id")
    if not user_id:
        user_id = str(user.get("_id", email))

    access_token = create_access_token(data={"sub": email, "user_id": user_id})
    return {"access_token": access_token, "token_type": "bearer", "email": email}

@router.get("/me")
async def get_me(current_user: str = Depends(get_current_user)):
    user = await users_collection.find_one({"email": current_user})
    user_id = user.get("user_id") if user else current_user
    return {"email": current_user, "user_id": user_id}
