# This library converts text into semantic vectors locally(no API calls)
from sentence_transformers import SentenceTransformer

# Load a pre-trained embedding model
# all-MiniLM-L6-v2 is:
# - Small
# - Fast
# - High quality for semantic similarity
# - Outputs vectors of size 384
model = SentenceTransformer("all-MiniLM-L6-v2")

def generate_embedding(text:str) -> list:
    """
    Convert a piece of text into a semantic embedding.

    WHY this function exists:
    - Single responsibility: text → vector
    - Reusable for both document chunks and user queries
    """
    # Encode the text into a numerical vector
    # The model understands semantic meaning, not just keywords
    embedding = model.encode(text)

    # Convert NumPy array to Python list
    # This makes it easier to store and pass around
    return embedding.tolist()

