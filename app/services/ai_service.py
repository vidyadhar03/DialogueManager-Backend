import json
from openai import OpenAI
from app.core.config import settings
from app.core.prompts import DIRECTOR_SYSTEM_PROMPT

client = OpenAI(api_key=settings.OPENAI_API_KEY)

async def analyze_lines(lines):
    user_content = "Analyze these lines and provide the JSON mapping:\n\n"
    for line in lines:
        user_content += f"--- Line ID: {line.id} ---\n"
        user_content += f"Context: {line.action} | SFX: {line.sfx}\n"
        user_content += f"Characters Present: {', '.join(line.characters)}\n"
        user_content += f"Dialogue: \"{line.dialogue}\"\n\n"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        response_format={ "type": "json_object" },
        temperature=0.7
    )
    return json.loads(response.choices[0].message.content)