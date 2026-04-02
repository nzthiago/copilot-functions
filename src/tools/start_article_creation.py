import uuid

from pydantic import BaseModel, Field


class StartArticleCreationParams(BaseModel):
    prompt: str = Field(description="A prompt describing the article to create")


async def start_article_creation(params: StartArticleCreationParams) -> str:
    """Start creating a new article from a prompt. Returns a JSON object with an article_id that can be used to poll for status."""
    article_id = str(uuid.uuid4())
    return f'{{"article_id": "{article_id}", "status": "Running", "message": "Article creation started"}}'
