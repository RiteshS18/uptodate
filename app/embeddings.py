import os

from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None
_client: OpenAI | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_client() -> OpenAI:
    """Return a singleton OpenAI client. Reads OPENAI_API_KEY from environment."""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your .env file."
            )
        _client = OpenAI(api_key=api_key, max_retries=0)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_model()
    # encode returns a numpy array; convert to plain Python lists for Chroma
    embeddings = model.encode(texts, convert_to_numpy=True)
    return [emb.tolist() for emb in embeddings]
