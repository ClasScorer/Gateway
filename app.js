const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const cors = require('cors');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');
const swaggerJsdoc = require('swagger-jsdoc');
const swaggerUi = require('swagger-ui-express');

const app = express();

// Enable CORS
app.use(cors());

// Swagger definition
const swaggerOptions = {
  definition: {
    openapi: '3.0.0',
    info: {
      title: 'Face Analysis Gateway API',
      version: '1.0.0',
      description: 'API Gateway for Face Analysis Services including Recognition, Attention Detection, and Face Localization',
      contact: {
        name: 'API Support'
      }
    },
    servers: [
      {
        url: 'http://localhost:80',
        description: 'Local Development'
      }
    ],
    components: {
      schemas: {
        Error: {
          type: 'object',
          properties: {
            error: { type: 'string' },
            message: { type: 'string' },
            details: { type: 'string' }
          }
        },
        ProcessFrameResponse: {
          type: 'object',
          properties: {
            lecture_id: { type: 'string' },
            timestamp: { type: 'string', format: 'date-time' },
            total_faces: { type: 'integer' },
            faces: {
              type: 'array',
              items: {
                type: 'object',
                properties: {
                  person_id: { type: 'string' },
                  recognition_status: { type: 'string', enum: ['new', 'found'] },
                  attention_status: { type: 'string', enum: ['focused', 'unfocused'] },
                  hand_raising_status: {
                    type: 'object',
                    properties: {
                      is_hand_raised: { type: 'boolean' },
                      confidence: { type: 'number', format: 'float' },
                      hand_position: {
                        type: 'object',
                        properties: {
                          x: { type: 'number' },
                          y: { type: 'number' }
                        }
                      }
                    }
                  },
                  confidence: { type: 'number', format: 'float' },
                  bounding_box: {
                    type: 'object',
                    properties: {
                      x: { type: 'number' },
                      y: { type: 'number' },
                      width: { type: 'number' },
                      height: { type: 'number' }
                    }
                  }
                }
              }
            },
            summary: {
              type: 'object',
              properties: {
                new_faces: { type: 'integer' },
                known_faces: { type: 'integer' },
                focused_faces: { type: 'integer' },
                unfocused_faces: { type: 'integer' },
                hands_raised: { type: 'integer' }
              }
            }
          }
        }
      }
    }
  },
  apis: ['./app.js']
};

const swaggerSpec = swaggerJsdoc(swaggerOptions);

// Serve Swagger documentation
app.use('/api-docs', swaggerUi.serve, swaggerUi.setup(swaggerSpec));
app.get('/api-docs.json', (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.send(swaggerSpec);
});

// Configure multer for memory storage
const upload = multer({ 
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 10 * 1024 * 1024 // 10MB limit
  }
});

// Configuration for services
const SERVICES = {
  RECOGNITION: {
    url: process.env.RECOGNITION_URL || 'http://recognition:23121',
    pathRewrite: {
      '^/api/recognition': ''
    }
  },
  ATTENTION: {
    url: process.env.ATTENTION_URL || 'http://attention:23123',
    pathRewrite: {
      '^/api/attention': ''
    }
  },
  LOCALIZATION: {
    url: process.env.LOCALIZATION_URL || 'http://localization:23122',
    pathRewrite: {
      '^/api/localization': ''
    }
  },
  HANDRAISING: {
    url: process.env.HANDRAISING_URL || 'http://handraising:23124',
    pathRewrite: {
      '^/api/handraising': ''
    }
  }
};

// Process pipeline for a single face
async function processFace(faceImage, boundingBox, lectureId, timestamp) {
  try {
    // Step 1: Recognition
    const recognitionForm = new FormData();
    recognitionForm.append('image', Buffer.from(faceImage, 'base64'), {
      filename: 'face.jpg',
      contentType: 'image/jpeg'
    });
    
    const recognitionResponse = await axios.post(
      `${SERVICES.RECOGNITION.url}/identify`,
      recognitionForm,
      { headers: recognitionForm.getHeaders() }
    );

    // Step 2: Attention Detection
    const attentionForm = new FormData();
    attentionForm.append('image', Buffer.from(faceImage, 'base64'), {
      filename: 'face.jpg',
      contentType: 'image/jpeg'
    });
    attentionForm.append('face_id', recognitionResponse.data.person_id);

    const attentionResponse = await axios.post(
      `${SERVICES.ATTENTION.url}/detect-face-attention`,
      attentionForm,
      { headers: attentionForm.getHeaders() }
    );

    // Step 3: Hand Raising Detection
    const handRaisingForm = new FormData();
    handRaisingForm.append('image', Buffer.from(faceImage, 'base64'), {
      filename: 'face.jpg',
      contentType: 'image/jpeg'
    });
    handRaisingForm.append('student_id', recognitionResponse.data.person_id);
    handRaisingForm.append('timestamp', timestamp);

    const handRaisingResponse = await axios.post(
      `${SERVICES.HANDRAISING.url}/detect-hand-raising`,
      handRaisingForm,
      { headers: handRaisingForm.getHeaders() }
    );

    return {
      person_id: recognitionResponse.data.person_id,
      recognition_status: recognitionResponse.data.status,
      attention_status: attentionResponse.data.attention_status,
      hand_raising_status: {
        is_hand_raised: handRaisingResponse.data.is_hand_raised,
        confidence: handRaisingResponse.data.confidence,
        hand_position: handRaisingResponse.data.hand_position
      },
      confidence: attentionResponse.data.confidence,
      bounding_box: boundingBox
    };

  } catch (error) {
    console.error('Error processing face:', error);
    throw error;
  }
}

/**
 * @swagger
 * /api/process-frame:
 *   post:
 *     summary: Process a frame from a lecture
 *     description: Analyzes a frame to detect faces, recognize people, and determine attention status
 *     tags: [Frame Processing]
 *     requestBody:
 *       required: true
 *       content:
 *         multipart/form-data:
 *           schema:
 *             type: object
 *             properties:
 *               image:
 *                 type: string
 *                 format: binary
 *                 description: The frame image to process
 *               lectureId:
 *                 type: string
 *                 description: Unique identifier for the lecture session
 *               timestamp:
 *                 type: string
 *                 format: date-time
 *                 description: ISO 8601 timestamp from the frontend
 *             required:
 *               - image
 *               - lectureId
 *               - timestamp
 *     responses:
 *       200:
 *         description: Frame successfully processed
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ProcessFrameResponse'
 *       400:
 *         description: Invalid input
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Error'
 *       500:
 *         description: Server error
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/Error'
 */
app.post('/api/process-frame', upload.single('image'), async (req, res) => {
  try {
    const lectureId = req.body.lectureId;
    const timestamp = req.body.timestamp;

    // Validate required fields
    if (!lectureId) {
      return res.status(400).json({ error: 'Lecture ID is required' });
    }
    if (!timestamp) {
      return res.status(400).json({ error: 'Timestamp is required' });
    }
    if (!req.file) {
      return res.status(400).json({ error: 'No image provided' });
    }

    // Validate timestamp format
    if (!isValidISOString(timestamp)) {
      return res.status(400).json({ error: 'Invalid timestamp format. Must be ISO 8601' });
    }

    // Step 1: Get face coordinates from Localization service
    const localizationForm = new FormData();
    localizationForm.append('image', req.file.buffer, {
      filename: 'frame.jpg',
      contentType: req.file.mimetype
    });

    // Get both coordinates and face images
    const [coordsResponse, facesResponse] = await Promise.all([
      axios.post(
        `${SERVICES.LOCALIZATION.url}/localize-coords`,
        localizationForm,
        { headers: localizationForm.getHeaders() }
      ),
      axios.post(
        `${SERVICES.LOCALIZATION.url}/localize-faces`,
        localizationForm,
        { headers: localizationForm.getHeaders() }
      )
    ]);

    const localizedFaces = facesResponse.data.faces;
    const faceCoordinates = coordsResponse.data.coordinates;

    // Step 2: Process each face in parallel with its coordinates
    const faceProcessingPromises = localizedFaces.map((faceImage, index) => 
      processFace(faceImage, faceCoordinates[index], lectureId, timestamp)
    );

    const results = await Promise.all(faceProcessingPromises);

    // Step 3: Aggregate results
    const response = {
      lecture_id: lectureId,
      timestamp: timestamp,  // Use the frontend's timestamp
      total_faces: localizedFaces.length,
      faces: results,
      summary: {
        new_faces: results.filter(r => r.recognition_status === 'new').length,
        known_faces: results.filter(r => r.recognition_status === 'found').length,
        focused_faces: results.filter(r => r.attention_status === 'focused').length,
        unfocused_faces: results.filter(r => r.attention_status === 'unfocused').length,
        hands_raised: results.filter(r => r.hand_raising_status.is_hand_raised).length
      }
    };

    res.json(response);

  } catch (error) {
    console.error('Pipeline Error:', error);
    res.status(500).json({
      error: 'Pipeline Error',
      message: error.message,
      details: error.response?.data || 'No additional details available'
    });
  }
});

// Helper function to validate ISO 8601 timestamp
function isValidISOString(str) {
  try {
    const d = new Date(str);
    return d instanceof Date && !isNaN(d) && d.toISOString() === str;
  } catch (e) {
    return false;
  }
}

// Error handler middleware
const errorHandler = (err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ 
    error: 'Internal Server Error',
    message: err.message
  });
};

/**
 * @swagger
 * /health:
 *   get:
 *     summary: Health check endpoint
 *     description: Check if the gateway service is running
 *     tags: [Health]
 *     responses:
 *       200:
 *         description: Service is healthy
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 status:
 *                   type: string
 *                   example: ok
 *                 message:
 *                   type: string
 *                   example: Gateway is running
 */
app.get('/health', (req, res) => {
  res.json({ status: 'ok', message: 'Gateway is running' });
});

// Proxy middleware for direct service access (if needed)
Object.entries(SERVICES).forEach(([service, config]) => {
  app.use(`/api/${service.toLowerCase()}`, createProxyMiddleware({
    target: config.url,
    changeOrigin: true,
    pathRewrite: config.pathRewrite,
    onError: (err, req, res) => {
      console.error(`${service} Service Error:`, err);
      res.status(503).json({
        error: 'Service Unavailable',
        message: `${service} service is currently unavailable`
      });
    }
  }));
});

// Add error handler
app.use(errorHandler);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Gateway running on port ${PORT}`);
}); 