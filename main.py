from fastapi import FastAPI
from pydantic import BaseModel
import subprocess
import json
from checkcodetype import detect_language
from checkcodetype import fetch_document_by_id
from pymongo import MongoClient
from bson.objectid import ObjectId
import logging
import os
from datetime import datetime

# Configure logging
log_directory = "logs"
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

# Set up logging with both file and console handlers
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_directory, f"api_{datetime.now().strftime('%Y%m%d')}.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("py-api")

app = FastAPI()

# MongoDB connection
def get_mongodb_connection():
    try:
        logger.info("Establishing MongoDB connection")
        client = MongoClient("mongodb+srv://admin:7vNJvFHGPVvbWBRD@syntaxsentry.rddho.mongodb.net/?retryWrites=true&w=majority&appName=syntaxsentry")
        db = client["test"]
        logger.info("MongoDB connection established successfully")
        return db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {str(e)}")
        raise

# Function to store AI responses in MongoDB
def store_ai_response(document_id, event_type, response_data, status="success"):
    try:
        logger.info(f"Storing AI response for document_id: {document_id}, event_type: {event_type}")
        db = get_mongodb_connection()
        airesponse_collection = db["airesponse"]
        
        # Prepare the document to insert
        response_doc = {
            "documentId": ObjectId(document_id),  # Convert document_id to ObjectId
            "eventType": event_type,
            "response": response_data,
            "status": status,
            "createdAt": datetime.utcnow(),  # Store createdAt timestamp
            "__v": 0  # Explicitly setting __v to 0
        }
        
        # Insert the document
        result = airesponse_collection.insert_one(response_doc)
        logger.info(f"AI response stored successfully with ID: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error storing AI response: {str(e)}")
        return None

class ScriptRequest(BaseModel):
    script_name: str
    object_id: str  # New field to pass object_id

@app.post("/execute")
async def execute_code(request: ScriptRequest):
    logger.info(f"Received request to execute script: {request.script_name} for object_id: {request.object_id}")
    
    if request.script_name not in ["paste.py", "copymain.py", "keymain.py","cpp.py","py.py","java.py","javascript.py","tab.py"]:
        logger.warning(f"Invalid script name requested: {request.script_name}")
        return {"error": "Invalid script name"}

    try:
        # Determine event type based on script name
        event_type = "copy" if request.script_name == "copymain.py" else "paste" if request.script_name == "paste.py" else "key" if request.script_name == "keymain.py" else "tab" if request.script_name == "tab.py" else "code"
        logger.info(f"Determined event_type: {event_type}")
        
        # Pass object_id as an argument to the script
        if(request.script_name in ["paste.py", "copymain.py", "keymain.py","tab.py"]):
            logger.info(f"Executing script directly: {request.script_name}")
            output = subprocess.run(
                ["python3", request.script_name, request.object_id], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
        else:
            logger.info(f"Detecting language for document: {request.object_id}")
            document = fetch_document_by_id(request.object_id)
            if not document:
                logger.error(f"Document not found for ID: {request.object_id}")
                raise Exception(f"Document not found for ID: {request.object_id}")
                
            language = detect_language(document['code'])
            logger.info(f"Detected language: {language}")
            
            if language == 'Java':
                logger.info(f"Executing Java script for document: {request.object_id}")
                output = subprocess.run(
                    ["python3", 'java.py', request.object_id], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
            elif language == 'Python':
                logger.info(f"Executing Python script for document: {request.object_id}")
                output = subprocess.run(
                    ["python3", 'py.py', request.object_id], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
            elif language == 'C++':
                logger.info(f"Executing C++ script for document: {request.object_id}")
                output = subprocess.run(
                    ["python3", 'cpp.py', request.object_id], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
            elif language == 'Javascript':
                logger.info(f"Executing JavaScript script for document: {request.object_id}")
                output = subprocess.run(
                    ["python3", 'javascript.py', request.object_id], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
            else:
                logger.warning(f"Unsupported language detected: {language}")
                output = subprocess.CompletedProcess(args=[], returncode=0)
                output.stdout = "could not find language among cpp,java,js,py"
                output.stderr = "500"

        stdout = output.stdout.strip()
        stderr = output.stderr.strip()

        if stderr:
            logger.error(f"Error executing script {request.script_name}: {stderr}")
            # Store error response in MongoDB
            error_response = {"error": stderr}
            store_ai_response(
                document_id=request.object_id,
                event_type=event_type,
                response_data={
                    "script_name": request.script_name,
                    "object_id": request.object_id,
                    "error": stderr
                },
                status="error"
            )
            return error_response

        # Convert output to JSON if possible
        try:
            logger.info(f"Processing script output for {request.script_name}")
            response_data = json.loads(stdout)
            
            # Store successful response in MongoDB
            logger.info(f"Storing successful response for {request.script_name}")
            store_ai_response(
                document_id=request.object_id,
                event_type=event_type,
                response_data={
                    "script_name": request.script_name,
                    "object_id": request.object_id,
                    **response_data
                }
            )
            
            return response_data
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format in script output: {stdout[:100]}...")
            # Store error response in MongoDB
            error_response = {"error": "Invalid JSON format in script output", "raw_output": stdout}
            store_ai_response(
                document_id=request.object_id,
                event_type=event_type,
                response_data={
                    "script_name": request.script_name,
                    "object_id": request.object_id,
                    "error": "Invalid JSON format in script output",
                    "raw_output": stdout
                },
                status="error"
            )
            return error_response

    except Exception as e:
        logger.critical(f"Exception during script execution: {str(e)}", exc_info=True)
        # Store error response in MongoDB
        error_response = {"error": str(e)}
        store_ai_response(
            document_id=request.object_id,
            event_type=event_type,
            response_data={
                "script_name": request.script_name,
                "object_id": request.object_id,
                "error": str(e)
            },
            status="error"
        )
        return error_response
