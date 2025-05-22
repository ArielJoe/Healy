import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

class AzureClient:
    def __init__(self):
        self.client = AzureOpenAI(
            api_version=os.getenv("AZURE_API_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY")
        )
    
    def get_response(self, messages, max_completion_tokens=100000):
        try:
            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=messages,
                max_completion_tokens=max_completion_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"
        