import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(".env")
api_key = os.getenv("GROQ_API_KEY")
client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

model = "openai/gpt-oss-120b"
try:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(f"✅ {model} works! Output: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ {model} failed: {e}")
