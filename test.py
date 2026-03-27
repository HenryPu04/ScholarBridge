import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

print("--- Available Embedding Models ---")
for m in genai.list_models():
    if 'embedContent' in m.supported_generation_methods:
        print(f"Model Name: {m.name}")