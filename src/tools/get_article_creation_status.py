import asyncio
import random

from pydantic import BaseModel, Field


class GetArticleCreationStatusParams(BaseModel):
    article_id: str = Field(description="The article ID (GUID) returned by start_article_creation")
    wait_before_polling: float = Field(
        description="Number of seconds to wait before returning a result (0 or more). Allows the caller to implement backoff.",
        ge=0,
    )


_RUNNING_MESSAGES = [
    "Researching topic and gathering sources...",
    "Generating article outline...",
    "Writing introduction and key sections...",
    "Creating images and diagrams...",
    "Reviewing content for accuracy...",
    "Formatting and applying style guidelines...",
    "Generating citations and references...",
    "Optimizing for readability...",
    "Running final quality checks...",
]


async def get_article_creation_status(params: GetArticleCreationStatusParams) -> str:
    """Poll the status of an article creation job. Returns JSON with status (Running or Completed). Use wait_before_polling to add a delay before checking."""
    if params.wait_before_polling > 0:
        await asyncio.sleep(params.wait_before_polling)

    if random.random() < 0.25:
        return (
            f'{{"article_id": "{params.article_id}", "status": "Completed", '
            f'"url": "https://contoso.com/articles/{params.article_id}"}}'
        )

    message = random.choice(_RUNNING_MESSAGES)
    return f'{{"article_id": "{params.article_id}", "status": "Running", "message": "{message}"}}'
