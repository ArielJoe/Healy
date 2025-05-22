from utils.azure_handler import AzureClient

class Healy:
    def __init__(self):
        self.ai = AzureClient()
        
    def generate_response(self, user_input):
        messages = [
            {"role": "system", "content": "You're a professional fitness advisor."},
            {"role": "user", "content": user_input}
        ]
        return self.ai.get_response(messages)
    