from langchain.tools import tool
from langchain_core.tools import StructuredTool


@tool("customer_search", description="Search customer records.")
def search_customers(query: str, limit: int = 10) -> dict:
    """Search customer records."""
    return {"query": query, "limit": limit}


def summarize_ticket(ticket_id: str, style: str = "brief", runtime=None) -> str:
    """Summarize a support ticket."""
    return f"{ticket_id}:{style}"


ticket_summary_tool = StructuredTool.from_function(
    func=summarize_ticket,
    name="ticket_summary",
    description="Summarize a support ticket by ID.",
)
