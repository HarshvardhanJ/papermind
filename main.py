import os
from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel
import json


load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

client = Groq(api_key=api_key)

text = ""
with open("files/paper.txt", "r") as f:
    text = f.read()


class ResearchPaperSchema(BaseModel):
    title: str
    key_claim: str
    method_used: str
    main_result: str


response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {
            "role": "system",
            "content": "You are a expert researcher. Generate a structured JSON overview of the research paper by giving title, key claim, method used, main result.",
        },
        {"role": "user", "content": f"Here is the research paper text:\n\n{text}"},
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "research_paper_analysis",
            "schema": ResearchPaperSchema.model_json_schema(),
        },
    },
)


research_paper_analysis = ResearchPaperSchema.model_validate(
    json.loads(response.choices[0].message.content)
)
output = json.dumps(research_paper_analysis.model_dump(), indent=2)

with open("files/output.json", "w") as o:
    o.write(output)

print("done!")
