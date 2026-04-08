import json
from google import genai

class AIService:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        self.model_name = self.config.get("model_name", "gemini-flash-latest")

    def get_client(self, api_key):
        """Создает клиент Gemini для конкретного запроса."""
        if not api_key:
            return genai.Client() # Пытаемся использовать ADC/Browser если ключа нет
        return genai.Client(api_key=api_key)

    def generate_cards(self, api_key, user_prompt, count=5):
        """Генерирует список карточек на основе развернутой инструкции пользователя."""
        client = self.get_client(api_key)
        
        system_instructions = f"""
        You are an expert educator. Generate flashcards based on: "{user_prompt}"
        
        FORMAT RULES (STRICT):
        Front: [Question]
        Back: [Answer]
        ---
        (Repeat for {count} cards)
        
        Do NOT use markdown code blocks like ```. Just plain text.
        """
        
        response = client.models.generate_content(
            model=self.model_name,
            contents=system_instructions
        )
        
        cards = []
        raw_text = response.text
        # Очистка от возможных markdown-кавычек, если AI их все же добавил
        clean_text = raw_text.replace("```", "").replace("markdown", "").strip()
        
        blocks = clean_text.split("---")
        for block in blocks:
            if not block.strip(): continue
            
            # Ищем Front и Back в блоке
            front = ""
            back = ""
            for line in block.split("\n"):
                if "Front:" in line:
                    front = line.split("Front:", 1)[-1].strip()
                elif "Back:" in line:
                    back = line.split("Back:", 1)[-1].strip()
            
            if front and back:
                cards.append((front, back))
        
        if not cards:
            raise ValueError(f"AI returned text in wrong format. Raw response: {raw_text[:100]}...")
            
        return cards

    def check_answer(self, api_key, question, correct_answer, user_answer):
        """Проверяет ответ с использованием переданного ключа."""
        client = self.get_client(api_key)
        prompt = f"""
        Question: {question}
        Correct Answer: {correct_answer}
        User Answer: {user_answer}
        
        Is the User Answer semantically correct? 
        Respond with "YES" or "NO" followed by a very brief explanation (1 sentence).
        """
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text.strip()
