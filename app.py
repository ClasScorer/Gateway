from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import base64
from datetime import datetime
import logging
from dotenv import load_dotenv
import asyncio
import io
from starlette.responses import RedirectResponse

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


# Service configuration using environment variables
SERVICES = {
    "RECOGNITION": {
        "url": os.getenv("RECOGNITION_URL", "http://recognition:23123"),
    },
    "LOCALIZATION": {
        "url": os.getenv("LOCALIZATION_URL", "http://localhost:23120"),  # Updated default URL
    },
    "ATTENTION": {
        "url": os.getenv("ATTENTION_URL", "http://attention:23125"),
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
        datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False

# Process single face with all services
async def process_face(face_image: str, bounding_box: dict, lecture_id: str, timestamp: str) -> dict:
    try:
        # Remove file writing which could cause permission issues
        logger.info(f"Processing face with bounding box: {bounding_box}")
        
        # Create BytesIO object only once
        try:
            decoded_image = base64.b64decode(face_image)
            logger.info(f"Successfully decoded base64 image of length: {len(decoded_image)}")
        except Exception as e:
            logger.error(f"Base64 decoding error: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid base64 image: {str(e)}")
        
        # Transform bounding box for response
        transformed_bbox = {
            "x": bounding_box["x_min"],
            "y": bounding_box["y_min"],
            "width": bounding_box["x_max"] - bounding_box["x_min"],
            "height": bounding_box["y_max"] - bounding_box["y_min"]
        }
        
        # Initialize result with default values
        result = {
            "person_id": "unknown",
            "recognition_status": "failed",
            "attention_status": "UNKNOWN",
            "hand_raising_status": {
                "is_hand_raised": False,
                "confidence": 0.0,
                "hand_position": None
            },
            "confidence": 0.0,
            "bounding_box": transformed_bbox
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Recognition
            try:
                recognition_response = await client.post(
                    f"{SERVICES['RECOGNITION']['url']}/identify",
                    files={"image": ("face.jpg", io.BytesIO(decoded_image), "image/jpeg")}
                )
                logger.info(f"Recognition service response status: {recognition_response.status_code}")
                
                if recognition_response.status_code != 200:
                    logger.error(f"Recognition service error: {recognition_response.text}")
                else:
                    recognition_data = recognition_response.json()
                    logger.info(f"Recognition response: {recognition_data}")
                    result["person_id"] = recognition_data["person_id"]
                    result["recognition_status"] = recognition_data["status"]
            except Exception as e:
                logger.error(f"Recognition error: {str(e)}")
            
            # Step 2: Attention Detection
            try:
                attention_form = {
                    "file": ("face.jpg", io.BytesIO(decoded_image), "image/jpeg"),
                    "face_id": (None, str(result["person_id"])),
                    "lecture_id": (None, str(lecture_id)),
                    "timestamp": (None, str(timestamp))
                }
                
                attention_response = await client.post(
                    f"{SERVICES['ATTENTION']['url']}/detect-face-attention",
                    files=attention_form
                )
                logger.info(f"Attention service response status: {attention_response.status_code}")
                
                if attention_response.status_code != 200:
                    logger.error(f"Attention service error: {attention_response.text}")
                else:
                    attention_data = attention_response.json()
                    logger.info(f"Attention response: {attention_data}")
                    result["attention_status"] = attention_data["attention_status"]
                    result["confidence"] = attention_data["confidence"]
            except Exception as e:
                logger.error(f"Attention error: {str(e)}")
            
            # Step 3: Hand Raising Detection
            try:
                hand_raising_form = {
                    "file": ("face.jpg", io.BytesIO(decoded_image), "image/jpeg"),
                    "student_id": (None, result["person_id"]),
                    "timestamp": (None, timestamp)
                }
                
                hand_raising_response = await client.post(
                    f"{SERVICES['HANDRAISING']['url']}/detect-hand-raising",
                    files=hand_raising_form
                )
                logger.info(f"Hand raising service response status: {hand_raising_response.status_code}")
                
                if hand_raising_response.status_code != 200:
                    logger.error(f"Hand raising service error: {hand_raising_response.text}")
                else:
                    hand_raising_data = hand_raising_response.json()
                    logger.info(f"Hand raising response: {hand_raising_data}")
                    result["hand_raising_status"] = {
                        "is_hand_raised": hand_raising_data["is_hand_raised"],
                        "confidence": hand_raising_data["confidence"],
                        "hand_position": hand_raising_data["hand_position"]
                    }
            except Exception as e:
                logger.error(f"Hand raising error: {str(e)}")
            
            logger.info(f"Successfully processed face with available services")
            return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing face: {str(e)}")
        # Return basic information about the face without failing completely
        return {
            "person_id": "error",
            "recognition_status": "error",
            "attention_status": "ERROR",
            "hand_raising_status": {
                "is_hand_raised": False,
                "confidence": 0.0,
                "hand_position": None
            },
            "confidence": 0.0,
            "bounding_box": transformed_bbox
        }

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
            # Send image to localization service
            localization_response = await client.post(
                f"{SERVICES['LOCALIZATION']['url']}/localize-image/",
                files={"file": (image.filename, image_content, image.content_type)}
            )
            if localization_response.status_code != 200:
                raise HTTPException(status_code=502, detail="Localization service error with sending image")

            # Log response for debugging
            logger.info(f"Localization response status: {localization_response.status_code}")
            try:
                localization_data = localization_response.json()
                logger.info("Localization response data received successfully")
            except Exception as e:
                logger.error(f"Failed to parse localization response as JSON: {str(e)}")
                raise HTTPException(status_code=502, detail=f"Invalid response from localization service: {str(e)}")

            # Get face coordinates
            coords_response = await client.get(
                f"{SERVICES['LOCALIZATION']['url']}/localize-coords"
            )
            if coords_response.status_code != 200:
                raise HTTPException(status_code=502, detail="Localization service error with face coordinates")
            
            # Log coordinates response for debugging
            logger.info(f"Coordinates response status: {coords_response.status_code}")
            try:
                coords_data = coords_response.json()
                logger.info(f"Coordinates data received with {len(coords_data.get('bounding_boxes', []))} boxes")
            except Exception as e:
                logger.error(f"Failed to parse coordinates response as JSON: {str(e)}")
                raise HTTPException(status_code=502, detail=f"Invalid response from coordinates endpoint: {str(e)}")
            
            # Get extracted faces
            faces_response = await client.get(
                f"{SERVICES['LOCALIZATION']['url']}/localized-image"
            )
            if faces_response.status_code != 200:
                raise HTTPException(status_code=502, detail="Localization service error with face extraction")

            # Log faces response for debugging
            logger.info(f"Faces response status: {faces_response.status_code}")
            try:
                faces_data = faces_response.json()
                logger.info(f"Faces data received with {len(faces_data.get('images', []))} images")
            except Exception as e:
                logger.error(f"Failed to parse faces response as JSON: {str(e)}")
                raise HTTPException(status_code=502, detail=f"Invalid response from localized-image endpoint: {str(e)}")

        # Parse responses
        try:
            localized_faces = [face["image"] for face in faces_data["images"]]
            face_coordinates = coords_data["bounding_boxes"]
            
            logger.info(f"Extracted {len(localized_faces)} faces and {len(face_coordinates)} coordinates")
        except KeyError as e:
            logger.error(f"Missing key in response: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Unexpected response format: missing key {str(e)}")
        except Exception as e:
            logger.error(f"Error parsing response data: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to process response data: {str(e)}")

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
        try:
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
        except Exception as e:
            logger.error(f"Error aggregating results: {str(e)}")
            raise HTTPException(
                status_code=500, 
                detail={
                    "error": "Results Aggregation Error",
                    "message": str(e),
                    "details": "Error occurred while summarizing processed faces"
                }
            )
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Pipeline Error: {str(e)}\nTraceback: {error_traceback}")
        raise HTTPException(
            status_code=500, 
            detail={
                "error": "Pipeline Error",
                "message": str(e),
                "details": error_traceback
            }
        )

@app.get("/health")
async def health_check():
    """
    Health check endpoint
    
    Check if the gateway service is running
    """
    return {"status": "ok", "message": "Gateway is running"}

@app.get("/api/AssignID")
async def assignID():
    """Assign ID to a student, needs bounding box, reference image, and Student_ID."""
    return True


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
