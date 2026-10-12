from imaginary_agent import tool


@tool(name="search_web", description="Search web pages", version="1.0.0")
def search_web(query: str, top_k: int = 5) -> list[dict]:
    """Search web pages."""
    return []


@tool
def summarize(text: str, style: str = "short") -> str:
    """Summarize text for the user."""
    return text[:100]
