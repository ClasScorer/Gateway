# ClasScorer Gateway API

The Gateway API serves as the central entry point for the ClasScorer system, coordinating requests between client applications and microservices.

## Features

- Unified API endpoint for client applications
- Service discovery and routing
- Request aggregation from multiple microservices
- Health monitoring
- Error handling and retry logic

## Services Integrated

- **Recognition Service**: Face recognition and identification
- **Attention Service**: Student attention detection
- **Localization Service**: Face detection and extraction
- **Hand-Raising Service**: Detect if students are raising their hands

## Installation

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env file with your service URLs
```

## Configuration

The Gateway service uses environment variables for configuration:

- `PORT`: The port on which the Gateway API will run (default: 3000)
- `RECOGNITION_URL`: URL for the Recognition service
- `ATTENTION_URL`: URL for the Attention service 
- `LOCALIZATION_URL`: URL for the Localization service
- `HANDRAISING_URL`: URL for the Hand-Raising service
- `RATE_LIMIT`: Maximum requests per window (default: 100)
- `RATE_WINDOW`: Rate limiting window (default: 15m)
- `NODE_ENV`: Environment (development/production)

## Running the Gateway

Start the service with Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 3000 --reload
```

Or use the included service runner script:

```bash
../run-services.sh
```

## API Endpoints

### `/api/process-frame`

Process a frame to detect faces, recognize people, determine attention status, and detect hand raising.

**Request:**
- Method: POST
- Content-Type: multipart/form-data
- Body:
  - `image`: Image file
  - `lectureId`: String
  - `timestamp`: ISO 8601 timestamp

**Response:**
- JSON object with aggregated results from all services

### `/health`

Check if the Gateway service is running.

**Request:**
- Method: GET

**Response:**
- JSON status object

### `/api/{service}/{path}`

Proxy requests directly to individual services.

## Development

To run the Gateway in development mode with automatic reloading:

```bash
uvicorn app:app --reload
```

### Testing

You can use the Swagger UI to test API endpoints: