from pathlib import Path

from agent_tool_drift.scanner import scan_project


def test_openapi_adapter_resolves_local_schema_refs(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Ref API
  version: 1.0.0
paths:
  /search:
    post:
      operationId: search_records
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/SearchRequest"
      responses:
        "200":
          description: Search response
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/SearchResponse"
components:
  schemas:
    SearchRequest:
      type: object
      properties:
        query:
          type: string
      required:
        - query
    SearchResponse:
      type: object
      properties:
        results:
          type: array
          items:
            $ref: "#/components/schemas/SearchResult"
    SearchResult:
      type: object
      properties:
        title:
          type: string
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "search_records")

    assert tool.input_schema["required"] == ["body"]
    assert tool.input_schema["properties"]["body"]["properties"]["query"]["type"] == "string"
    items = tool.output_schema["properties"]["results"]["items"]
    assert items["properties"]["title"]["type"] == "string"


def test_openapi_operation_parameter_overrides_path_parameter_required(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Param API
  version: 1.0.0
paths:
  /records/{record_id}:
    parameters:
      - name: record_id
        in: path
        required: true
        schema:
          type: string
      - name: debug
        in: query
        required: true
        schema:
          type: boolean
    get:
      operationId: get_record
      parameters:
        - name: debug
          in: query
          required: false
          schema:
            type: boolean
      responses:
        "200":
          description: OK
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "get_record")

    assert "record_id" in tool.input_schema["required"]
    assert "debug" not in tool.input_schema["required"]
    assert tool.input_schema["properties"]["debug"]["metadata"]["in"] == "query"


def test_openapi_prefers_json_like_vendor_media_type(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Media API
  version: 1.0.0
paths:
  /events:
    post:
      operationId: create_event
      requestBody:
        content:
          text/plain:
            schema:
              type: string
          application/vnd.api+json:
            schema:
              type: object
              properties:
                data:
                  type: object
      responses:
        "200":
          description: OK
          content:
            text/plain:
              schema:
                type: string
            application/vnd.api+json:
              schema:
                type: object
                properties:
                  result:
                    type: string
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "create_event")

    body_schema = tool.input_schema["properties"]["body"]
    assert body_schema["type"] == "object"
    assert "data" in body_schema["properties"]
    assert tool.output_schema["type"] == "object"
    assert "result" in tool.output_schema["properties"]


def test_openapi_reads_other_success_response_statuses(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Response API
  version: 1.0.0
paths:
  /batch:
    post:
      operationId: batch_update
      responses:
        207:
          description: Multi-status response
          content:
            application/json:
              schema:
                type: object
                properties:
                  statuses:
                    type: array
                    items:
                      type: string
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "batch_update")

    assert tool.output_schema["type"] == "object"
    assert tool.output_schema["properties"]["statuses"]["type"] == "array"


def test_openapi_ignores_non_http_method_path_item_keys(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Weird API
  version: 1.0.0
paths:
  /records:
    123:
      description: malformed extension emitted by a generator
    get:
      operationId: list_records
      responses:
        "200":
          description: OK
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)

    assert [tool.name for tool in snapshot.tools if tool.kind == "openapi"] == ["list_records"]
    assert "adapter_errors" not in snapshot.environment


def test_openapi_disambiguates_parameters_with_same_name_in_different_locations(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Duplicate Param API
  version: 1.0.0
paths:
  /records/{id}:
    get:
      operationId: get_record
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
        - name: id
          in: query
          required: false
          schema:
            type: integer
      responses:
        "200":
          description: OK
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "get_record")
    properties = tool.input_schema["properties"]

    assert set(properties) == {"path_id", "query_id"}
    assert properties["path_id"]["type"] == "string"
    assert properties["path_id"]["metadata"]["name"] == "id"
    assert properties["path_id"]["metadata"]["in"] == "path"
    assert properties["query_id"]["type"] == "integer"
    assert tool.input_schema["required"] == ["path_id"]


def test_openapi_request_body_does_not_overwrite_body_parameter(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: Body Param API
  version: 1.0.0
paths:
  /events:
    post:
      operationId: create_event
      parameters:
        - name: body
          in: query
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                event_id:
                  type: string
      responses:
        "200":
          description: OK
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "create_event")
    properties = tool.input_schema["properties"]

    assert properties["body"]["type"] == "string"
    assert properties["request_body"]["type"] == "object"
    assert tool.input_schema["required"] == ["body", "request_body"]
