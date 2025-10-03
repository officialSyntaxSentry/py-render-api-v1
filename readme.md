# Syntax Sentry API

A FastAPI-based service for analyzing code patterns and detecting suspicious coding behaviors across multiple programming languages.

## Features

- **Multi-language Support**: Analyzes Python, Java, C++, and JavaScript code
- **Behavioral Analysis**: Detects copy, paste, keystroke, and tab patterns
- **MongoDB Integration**: Stores analysis results and responses
- **Comprehensive Logging**: Detailed logging for debugging and monitoring
- **RESTful API**: Clean API endpoints for integration

## API Endpoints

### POST /execute
Execute code analysis scripts for different programming languages and behaviors.

**Request Body:**
```json
{
  "script_name": "cpp.py",
  "object_id": "67f559c9dfb01510b8393ffd"
}
```

**Supported Scripts:**
- `paste.py` - Paste behavior analysis
- `copymain.py` - Copy behavior analysis  
- `keymain.py` - Keystroke analysis
- `tab.py` - Tab usage analysis
- `cpp.py` - C++ code analysis
- `py.py` - Python code analysis
- `java.py` - Java code analysis
- `javascript.py` - JavaScript code analysis

**Response:**
```json
{
  "suspiciousness_percentage": 33.5,
  "reasons": [
    "Inconsistent spacing around operators found in ~100.0% of relevant lines.",
    "Lack of TODO/FIXME markers, often present in human development cycles."
  ],
  "factor_scores": {
    "comment_density": {
      "score": 0.8,
      "details": "0.00 (0/1)"
    }
  }
}
```

## Quick Start

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd py-api
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp env.example .env
   # Edit .env with your configuration
   ```

4. **Run the application**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Access the API**
   - API: http://localhost:8000
   - Interactive docs: http://localhost:8000/docs

### Docker Deployment

1. **Build and run with Docker Compose**
   ```bash
   docker-compose up --build
   ```

2. **Or build and run manually**
   ```bash
   docker build -t syntax-sentry-api .
   docker run -p 8000:8000 syntax-sentry-api
   ```

## Deployment Options

### 1. Render (Recommended)

1. **Connect your GitHub repository to Render**
2. **Create a new Web Service**
3. **Configure the service:**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Environment: `Python 3`
   - Plan: `Free` or `Starter`

4. **Set environment variables in Render dashboard:**
   - `MONGODB_URL`: Your MongoDB connection string
   - `MONGODB_DATABASE`: Database name
   - `LOG_LEVEL`: INFO
   - `ENVIRONMENT`: production

5. **Deploy**: Render will automatically deploy from your `render.yaml` configuration

### 2. Heroku

1. **Install Heroku CLI**
2. **Login and create app**
   ```bash
   heroku login
   heroku create your-app-name
   ```

3. **Set environment variables**
   ```bash
   heroku config:set MONGODB_URL="your-mongodb-url"
   heroku config:set MONGODB_DATABASE="test"
   heroku config:set LOG_LEVEL="INFO"
   heroku config:set ENVIRONMENT="production"
   ```

4. **Deploy**
   ```bash
   git push heroku main
   ```

### 3. Vercel

1. **Install Vercel CLI**
   ```bash
   npm i -g vercel
   ```

2. **Deploy**
   ```bash
   vercel --prod
   ```

3. **Set environment variables in Vercel dashboard**

### 4. Railway

1. **Connect GitHub repository to Railway**
2. **Configure environment variables**
3. **Deploy automatically**

### 5. DigitalOcean App Platform

1. **Create new app from GitHub**
2. **Configure build settings:**
   - Build Command: `pip install -r requirements.txt`
   - Run Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. **Set environment variables**
4. **Deploy**

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `MONGODB_URL` | MongoDB connection string | - | Yes |
| `MONGODB_DATABASE` | Database name | `test` | No |
| `API_HOST` | API host | `0.0.0.0` | No |
| `API_PORT` | API port | `8000` | No |
| `LOG_LEVEL` | Logging level | `INFO` | No |
| `LOG_DIRECTORY` | Log directory | `logs` | No |
| `SECRET_KEY` | Secret key for security | - | Yes (production) |
| `ENVIRONMENT` | Environment type | `development` | No |

## Project Structure

```
py-api/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── checkcodetype.py       # Language detection utilities
├── *.py                   # Analysis scripts for different languages
├── schema/                # JSON schema definitions
├── Dockerfile             # Docker configuration
├── docker-compose.yml     # Docker Compose setup
├── render.yaml           # Render deployment config
├── vercel.json           # Vercel deployment config
├── Procfile              # Heroku deployment config
├── env.example           # Environment variables template
└── README.md             # This file
```

## Dependencies

- **FastAPI**: Modern web framework for building APIs
- **Uvicorn**: ASGI server for running FastAPI
- **PyMongo**: MongoDB driver for Python
- **Radon**: Code complexity analysis
- **PyCodeStyle**: Python style checker

## Monitoring and Logging

- Logs are stored in the `logs/` directory
- Daily log rotation with timestamp-based filenames
- Console and file logging enabled
- Health check endpoint available at `/health`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For support and questions, please open an issue in the repository.
