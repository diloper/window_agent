import os
import sys
from google import genai

print("Starting API test...", flush=True)

api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: No API key found", flush=True)
    sys.exit(1)

print(f"API key found: {api_key[:10]}...", flush=True)

try:
    client = genai.Client(api_key=api_key)
    print("Client created successfully", flush=True)
    
    # Test with a simple prompt
    response = client.models.generate_content(
        model="gemma-4-31b-it",
        contents="Say hello in one word"
    )
    
    print(f"Response: {response.text}", flush=True)
    print("API test successful!", flush=True)
    
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
