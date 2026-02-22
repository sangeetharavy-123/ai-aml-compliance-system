
import vertexai
from vertexai.generative_models import GenerativeModel
from PyPDF2 import PdfReader
vertexai.init(
    project="hackathongdg-488107",
    location="us-central1"
)
model = GenerativeModel("gemini-2.0-flash-lite")
reader = PdfReader("policy.pdf")
text = ""
for page in reader.pages:
    text += page.extract_text()
print("PDF Loaded Successfully")
prompt = f"Explain this document simply:\n{text}"
response = model.generate_content(prompt)
print("\nAI Summary:\n")
print(response.text)
