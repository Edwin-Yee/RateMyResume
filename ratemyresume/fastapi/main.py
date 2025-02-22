import PyPDF2
import os 
import base64
import gridfs
import pymongo 
import motor 
import bson

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from pymongo import MongoClient
from typing import Union, Optional
from uuid import UUID
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from dotenv import load_dotenv
from io import BytesIO
from bson import ObjectId 
from base64 import b64decode

from comprehend import get_pii_words, edit_pdf

load_dotenv()

class Item(BaseModel):
    id: int
    major_tag: str
    description: str
    likes: int
    pdf_file: bytes  # Add this field to accept bytes for the PDF

mongodb_uri = os.getenv("URI")
database_name = os.getenv("NAME")
app = FastAPI()

origins = ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create MongoDB client
client = AsyncIOMotorClient(mongodb_uri)
db = client[database_name]
num_pages = None


@app.get("/")
async def read_root():
    print("READ ROOT")
    # Check if a PDF has been uploaded
    if num_pages is not None:
        return {"Number of pages in last uploaded PDF": num_pages}
    else:
        return {"message": "No PDF uploaded yet"}


@app.get("/get-all")
async def get_all_items():
    collection = db["items"]
    items = await collection.find().to_list(length=None)

    # Convert ObjectId to string
    for item in items:
        item["_id"] = str(item["_id"])

    return items


@app.get("/items/{item_id}")
async def read_item(item_id: str):
    try:
        # Manually convert the hexadecimal string to ObjectId
        item_id_obj = ObjectId(item_id)
    except bson.errors.InvalidId:
        # Handle the case when item_id is not a valid ObjectId
        raise HTTPException(status_code=400, detail="Invalid item_id")

    collection = db["items"]
    item = await collection.find_one({"_id": item_id_obj})
    
    if item:
        # Convert ObjectId to string for proper serialization
        item["_id"] = str(item["_id"])
        extract_pdf(item["pdf_file"])
        return item
    else:
        return {"message": "Item not found"}


def extract_pdf(pdf_file_base64):
    print("Extract PDF is working!!")
    # Decode the Base64 string, making sure that it contains only valid characters
    bytes = b64decode(pdf_file_base64, validate=True)

    # Perform a basic validation to make sure that the result is a valid PDF file
    # Be aware! The magic number (file signature) is not 100% reliable solution to validate PDF files
    # Moreover, if you get Base64 from an untrusted source, you must sanitize the PDF contents
    if bytes[0:4] != b'%PDF':
        raise ValueError('Missing the PDF file signature')

    # Write the PDF contents to a local file
    f = open('a NEW PDF.pdf', 'wb')
    f.write(bytes)
    f.close()


@app.post("/create-item")
async def create_item(item: Item):
    print("Create-item has been called!")
    # Example: Insert item details into MongoDB
    collection = db["items"]  # Replace "items" with your actual collection name
    result = await collection.insert_one(item.dict())

    if result.inserted_id:
        return {"message": "Item created successfully", "item_id": str(result.inserted_id)}
    else:
        raise HTTPException(status_code=500, detail="Failed to create item")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    global num_pages
    contents = await file.read()
    file_stream = BytesIO(contents)
    text_reader = PyPDF2.PdfReader(file_stream) 

    pdf_text = text_reader.pages[0].extract_text()
    pdf_bytes = await write_new_pdf(file) 
    num_pages = len(text_reader.pages)

    # Temporary comment out
    pii_words = ["Joe"]
    # pii_words = get_pii_words(pdf_text)
    # for word in pii_words:
    #     print(word)

    redacted_pdf_bytes  = edit_pdf(pdf_bytes, pii_words)

    # Return the redacted PDF bytes as a response
    return Response(content=redacted_pdf_bytes, media_type='application/pdf')


async def write_new_pdf(file):
    # Ensure the file position is at the beginning
    file.file.seek(0)

    # Read the file content as bytes
    pdf_bytes = file.file.read()

    return pdf_bytes


@app.put("/items/{item_id}")
async def update_item(item_id: int, item: Item):
    # Update item details in MongoDB based on item_id
    collection = db["items"]
    result = await collection.update_one({"item_id": item_id}, {"$set": item.dict()})
    
    if result.modified_count == 1:
        return {"message": "Item updated successfully"}
    else:
        return {"message": "Item not found"}

@app.put("/update-items/{item_id}")
async def update_item_details(item_id: int, updated_item: Item):
    # Example: Update item details in MongoDB based on item_id
    collection = db["items"]  # Replace "items" with your actual collection name
    result = await collection.update_one({"item_id": item_id}, {"$set": updated_item.dict()})
    
    if result.modified_count == 1:
        return {"message": "Item updated successfully"}
    else:
        return {"message": "Item not found"}
    
@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    for item in db:
        if item.id == item_id:
            db.remove(item)
            return      
    raise HTTPException(status_code=404, detail=f"User with id: {item_id} does not exist.")
    
if client:
    print("Connected to MongoDB")