from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum
import httpx
import os
import base64
from datetime import datetime
import logging
from dotenv import load_dotenv
import asyncio
import io
from starlette.responses import RedirectResponse
import json
import time
from starlette.middleware.base import BaseHTTPMiddleware
import uuid

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Face Analysis Gateway API",
    description="""API Gateway for Face Analysis Services including Recognition, Attention Detection, and Face Localization""",
    version="1.0.0",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add the middleware to the application
app.add_middleware(RequestLoggingMiddleware)

# Service configuration using environment variables
SERVICES = {
    "RECOGNITION": {
        "url": os.getenv("LOCALIZATION_URL", "http://localization:23122"),
    },
    "HANDRAISING": {
        "url": os.getenv("HANDRAISING_URL", "http://handraising:23124"),
    }
}

# Models for request and response validation
class Error(BaseModel):
    error: str
    message: str
    details: Optional[str] = None

class HandPosition(BaseModel):
    x: float
    y: float
    z: Optional[float] = None

class HandRaisingStatus(BaseModel):
    is_hand_raised: bool
    confidence: float
    hand_position: Optional[HandPosition] = None

class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float

class Face(BaseModel):
    person_id: str
    recognition_status: str
    attention_status: str
    hand_raising_status: HandRaisingStatus
    confidence: float
    bounding_box: BoundingBox

class Summary(BaseModel):
    new_faces: int
    known_faces: int
    focused_faces: int
    unfocused_faces: int
    hands_raised: int

class ProcessFrameResponse(BaseModel):
    lecture_id: str
    timestamp: str
    total_faces: int
    faces: List[Face]
    summary: Summary

# Helper function to validate ISO 8601 timestamp
def is_valid_iso_string(timestamp_str: str) -> bool:
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False

# Process single face with all services
async def process_face(face_image: str, bounding_box: dict, lecture_id: str, timestamp: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Recognition
            recognition_form = {
                "image": (
                    "face.jpg", 
                    base64.b64decode(face_image), 
                    "image/jpeg"
                )
            }
            recognition_response = await client.post(
                f"{SERVICES['RECOGNITION']['url']}/identify",
                files=recognition_form
            )
            if recognition_response.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Recognition service error: {recognition_response.text}")
            
            recognition_data = recognition_response.json()
            
            # Step 2: Attention Detection
            attention_form = {
                "image": (
                    "face.jpg", 
                    base64.b64decode(face_image), 
                    "image/jpeg"
                ),
                "face_id": (None, recognition_data["person_id"]),
                "lecture_id": (None, lecture_id),
                "timestamp": (None, timestamp)
            }
            attention_response = await client.post(
                f"{SERVICES['ATTENTION']['url']}/detect-face-attention",
                files=attention_form
            )
            if attention_response.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Attention service error: {attention_response.text}")
            
            attention_data = attention_response.json()
            
            # Step 3: Hand Raising Detection
            hand_raising_form = {
                "image": (
                    "face.jpg", 
                    base64.b64decode(face_image), 
                    "image/jpeg"
                ),
                "student_id": (None, recognition_data["person_id"]),
                "timestamp": (None, timestamp)
            }
            hand_raising_response = await client.post(
                f"{SERVICES['HANDRAISING']['url']}/detect-hand-raising",
                files=hand_raising_form
            )
            if hand_raising_response.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Hand raising service error: {hand_raising_response.text}")
            
            hand_raising_data = hand_raising_response.json()
            
            # Combine results
            return {
                "person_id": recognition_data["person_id"],
                "recognition_status": recognition_data["status"],
                "attention_status": attention_data["attention_status"],
                "hand_raising_status": {
                    "is_hand_raised": hand_raising_data["is_hand_raised"],
                    "confidence": hand_raising_data["confidence"],
                    "hand_position": hand_raising_data["hand_position"]
                },
                "confidence": attention_data["confidence"],
                "bounding_box": bounding_box
            }

    except httpx.RequestError as e:
        logger.error(f"Request error: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing face: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing face: {str(e)}")

@app.post("/api/process-frame", response_model=ProcessFrameResponse)
async def process_frame(
    image: UploadFile = File(...),
    lectureId: str = Form(...),
    timestamp: str = Form(...)
):
    """
    Process a frame from a lecture
    
    Analyzes a frame to detect faces, recognize people, and determine attention status
    """
    try:
        # Validate input
        if not lectureId:
            raise HTTPException(status_code=400, detail="Lecture ID is required")
        
        if not timestamp:
            raise HTTPException(status_code=400, detail="Timestamp is required")
        
        if not is_valid_iso_string(timestamp):
            raise HTTPException(status_code=400, detail="Invalid timestamp format. Must be ISO 8601")
        
        # Read image content
        image_content = await image.read()
        
        # Step 1: Get face coordinates from Localization service
        async with httpx.AsyncClient() as client:
            # Request face coordinates
            coords_response = await client.post(
                f"{SERVICES['LOCALIZATION']['url']}/localize-coords",
                files={"image": (image.filename, image_content, image.content_type)}
            )
            if coords_response.status_code != 200:
                raise HTTPException(status_code=502, detail="Localization service error with coordinates")
            
            # Request face images
            faces_response = await client.post(
                f"{SERVICES['LOCALIZATION']['url']}/localize-faces",
                files={"image": (image.filename, image_content, image.content_type)}
            )
            if faces_response.status_code != 200:
                raise HTTPException(status_code=502, detail="Localization service error with face extraction")

        # Parse responses
        localized_faces = faces_response.json()["faces"]
        face_coordinates = coords_response.json()["coordinates"]
        
        if len(localized_faces) != len(face_coordinates):
            logger.error("Mismatch between number of faces and coordinates")
            raise HTTPException(status_code=500, detail="Mismatch between detected faces and coordinates")

        # Step 2: Process each face in parallel
        face_processing_tasks = [
            process_face(face_image, face_coordinates[idx], lectureId, timestamp)
            for idx, face_image in enumerate(localized_faces)
        ]
        
        results = await asyncio.gather(*face_processing_tasks, return_exceptions=True)
        
        # Filter out exceptions and log errors
        processed_faces = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Face processing error: {str(result)}")
                continue
            processed_faces.append(result)
        
        # Step 3: Aggregate results
        response = {
            "lecture_id": lectureId,
            "timestamp": timestamp,
            "total_faces": len(processed_faces),
            "faces": processed_faces,
            "summary": {
                "new_faces": len([r for r in processed_faces if r["recognition_status"] == "new"]),
                "known_faces": len([r for r in processed_faces if r["recognition_status"] == "found"]),
                "focused_faces": len([r for r in processed_faces if r["attention_status"] == "FOCUSED"]),
                "unfocused_faces": len([r for r in processed_faces if r["attention_status"] == "UNFOCUSED"]),
                "hands_raised": len([r for r in processed_faces if r["hand_raising_status"]["is_hand_raised"]])
            }
        }
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pipeline Error: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail={
                "error": "Pipeline Error",
                "message": str(e),
                "details": "No additional details available"
            }
        )

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    
    Check if the gateway service is running
    """
    return {"status": "ok", "message": "Gateway is running"}

@app.get("/")
async def root():
    """Redirect to API documentation"""
    return RedirectResponse(url="/docs")

# Proxy routes for direct service access
@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy_endpoint(service: str, path: str, request: Request):
    """
    Proxy endpoint for direct service access
    """
    service_upper = service.upper()
    
    if service_upper not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Service '{service}' not found")
    
    service_url = SERVICES[service_upper]["url"]
    target_url = f"{service_url}/{path}"
    
    # Get all headers from the incoming request
    headers = dict(request.headers)
    headers.pop("host", None)  # Remove host header
    
    # Get the request method and body
    method = request.method
    body = await request.body()
    
    try:
        async with httpx.AsyncClient() as client:
            # Forward the request to the target service
            response = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                content=body,
                params=request.query_params,
                follow_redirects=True,
                timeout=30.0  # 30 second timeout
            )
            
            # Create FastAPI response from the service response
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type")
            )
            
    except httpx.RequestError as e:
        logger.error(f"Service Error ({service}): {str(e)}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Service Unavailable",
                "message": f"{service} service is currently unavailable",
                "details": str(e)
            }
        )