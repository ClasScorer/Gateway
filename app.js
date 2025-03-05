const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const cors = require('cors');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');

const app = express();

// Enable CORS
app.use(cors());

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
  }
};

// Process pipeline for a single face
async function processFace(faceImage, lectureId) {
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

    return {
      person_id: recognitionResponse.data.person_id,
      recognition_status: recognitionResponse.data.status,
      attention_status: attentionResponse.data.attention_status,
      confidence: attentionResponse.data.confidence
    };

  } catch (error) {
    console.error('Error processing face:', error);
    throw error;
  }
}

// Main processing route
app.post('/api/process-frame', upload.single('image'), async (req, res) => {
  try {
    const lectureId = req.body.lectureId;
    if (!lectureId) {
      return res.status(400).json({ error: 'Lecture ID is required' });
    }

    if (!req.file) {
      return res.status(400).json({ error: 'No image provided' });
    }

    // Step 1: Localization
    const localizationForm = new FormData();
    localizationForm.append('image', req.file.buffer, {
      filename: 'frame.jpg',
      contentType: req.file.mimetype
    });

    const localizationResponse = await axios.post(
      `${SERVICES.LOCALIZATION.url}/localize-faces`,
      localizationForm,
      { headers: localizationForm.getHeaders() }
    );

    const localizedFaces = localizationResponse.data.faces;

    // Step 2: Process each face in parallel
    const faceProcessingPromises = localizedFaces.map(faceImage => 
      processFace(faceImage, lectureId)
    );

    const results = await Promise.all(faceProcessingPromises);

    // Step 3: Aggregate results
    const response = {
      lecture_id: lectureId,
      timestamp: new Date().toISOString(),
      total_faces: localizedFaces.length,
      faces: results,
      summary: {
        new_faces: results.filter(r => r.recognition_status === 'new').length,
        known_faces: results.filter(r => r.recognition_status === 'found').length,
        focused_faces: results.filter(r => r.attention_status === 'focused').length,
        unfocused_faces: results.filter(r => r.attention_status === 'unfocused').length
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

// Error handler middleware
const errorHandler = (err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ 
    error: 'Internal Server Error',
    message: err.message
  });
};

// Health check endpoint
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