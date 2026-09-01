import os
from abc import ABC, abstractmethod
from typing import List
from loguru import logger
from app.rag.config import settings

class BaseEmbeddingsAdapter(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        pass


class OpenAIEmbeddingsAdapter(BaseEmbeddingsAdapter):
    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API Key is required for OpenAI Embeddings.")
        from langchain_openai import OpenAIEmbeddings
        self._embeddings = OpenAIEmbeddings(model=self.model_name, openai_api_key=self.api_key)
        self._dimension = 1536
        logger.info(f"[embeddings] Loading OpenAI ({self.model_name}), dimension: {self._dimension}")

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._embeddings.embed_query(text)


class EmbeddingFactory:
    @staticmethod
    def get_embeddings_adapter() -> BaseEmbeddingsAdapter:
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY") or ""
        model_name = getattr(settings, "embedding_model_name", "text-embedding-3-small")
        if "bge" in model_name.lower() or "models/" in model_name.lower():
            model_name = "text-embedding-3-small"
        return OpenAIEmbeddingsAdapter(model_name=model_name, api_key=api_key)

