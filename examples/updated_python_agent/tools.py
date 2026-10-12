from imaginary_agent import tool


@tool(name="search_web", description="Search the public web", version="2.0.0")
def search_web(query: str, top_k: int, safe_search: bool = True) -> dict:
    """Search the public web."""
    return {}


@tool
def summarize(text: str, format: str = "paragraph") -> dict:
    """Summarize text and return structured output."""
    return {"summary": text[:100]}
