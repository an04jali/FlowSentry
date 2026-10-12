import json
import sys


TOOLS = [
    {
        "name": "search_docs",
        "description": "Search local documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "results": {"type": "array"},
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "summarize_doc",
        "description": "Summarize a document by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "style": {"type": "string"},
            },
            "required": ["doc_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
        },
    },
]


def send(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {
                        "protocolVersion": message.get("params", {}).get("protocolVersion"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "example-mcp", "version": "0.1.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": TOOLS}})
        elif "id" in message:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )


if __name__ == "__main__":
    main()
