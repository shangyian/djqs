"""
Tests for the queries API.
"""

import json
from datetime import datetime
from http import HTTPStatus

import msgpack
from fastapi.testclient import TestClient
from freezegun import freeze_time
from pytest_mock import MockerFixture
from sqlmodel import Session

from djqs.config import Settings
from djqs.engine import process_query
from djqs.models.catalog import Catalog
from djqs.models.engine import Engine
from djqs.models.query import (
    Query,
    QueryCreate,
    QueryState,
    Results,
    StatementResults,
    decode_results,
    encode_results,
)


def test_submit_query(session: Session, client: TestClient) -> None:
    """
    Test ``POST /queries/``.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col",
    )
    payload = query_create.json(by_alias=True)
    assert payload == json.dumps(
        {
            "catalog_name": "test_catalog",
            "engine_name": "test_engine",
            "engine_version": "1.0",
            "submitted_query": "SELECT 1 AS col",
            "async_": False,
        },
    )

    with freeze_time("2021-01-01T00:00:00Z"):
        response = client.post(
            "/queries/",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    data = response.json()

    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1 AS col"
    assert data["executed_query"] == "SELECT 1 AS col"
    assert data["scheduled"] == "2021-01-01T00:00:00"
    assert data["started"] == "2021-01-01T00:00:00"
    assert data["finished"] == "2021-01-01T00:00:00"
    assert data["state"] == "FINISHED"
    assert data["progress"] == 1.0
    assert len(data["results"]) == 1
    assert data["results"][0]["sql"] == "SELECT 1 AS col"
    assert data["results"][0]["columns"] == [{"name": "col", "type": "STR"}]
    assert data["results"][0]["rows"] == [[1]]
    assert data["errors"] == []


def test_submit_query_msgpack(session: Session, client: TestClient) -> None:
    """
    Test ``POST /queries/`` using msgpack.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col",
    )
    payload = query_create.dict(by_alias=True)
    data = msgpack.packb(payload, default=encode_results)

    with freeze_time("2021-01-01T00:00:00Z"):
        response = client.post(
            "/queries/",
            data=data,
            headers={
                "Content-Type": "application/msgpack",
                "Accept": "application/msgpack; q=1.0, application/json; q=0.5",
            },
        )
    data = msgpack.unpackb(response.content, ext_hook=decode_results)

    assert response.headers.get("content-type") == "application/msgpack"
    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1 AS col"
    assert data["executed_query"] == "SELECT 1 AS col"
    assert data["scheduled"] == datetime(2021, 1, 1)
    assert data["started"] == datetime(2021, 1, 1)
    assert data["finished"] == datetime(2021, 1, 1)
    assert data["state"] == "FINISHED"
    assert data["progress"] == 1.0
    assert len(data["results"]) == 1
    assert data["results"][0]["sql"] == "SELECT 1 AS col"
    assert data["results"][0]["columns"] == [{"name": "col", "type": "STR"}]
    assert data["results"][0]["rows"] == [[1]]
    assert data["errors"] == []


def test_submit_query_errors(
    session: Session,
    client: TestClient,
) -> None:
    """
    Test ``POST /queries/`` with missing/invalid content type.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col",
    )
    payload = query_create.json(by_alias=True)

    response = client.post(
        "/queries/",
        data=payload,
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Content type must be specified"}

    response = client.post(
        "/queries/",
        data=payload,
        headers={
            "Content-Type": "application/protobuf",
            "Accept": "application/json",
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json() == {
        "detail": "Content type not accepted: application/protobuf",
    }

    response = client.post(
        "/queries/",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/protobuf"},
    )
    assert response.status_code == 406
    assert response.json() == {
        "detail": "Client MUST accept: application/json, application/msgpack",
    }


def test_submit_query_multiple_statements(session: Session, client: TestClient) -> None:
    """
    Test ``POST /queries/``.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col; SELECT 2 AS another_col",
    )

    with freeze_time("2021-01-01T00:00:00Z"):
        response = client.post(
            "/queries/",
            data=query_create.json(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    data = response.json()

    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1 AS col; SELECT 2 AS another_col"
    assert data["executed_query"] == "SELECT 1 AS col; SELECT 2 AS another_col"
    assert data["scheduled"] == "2021-01-01T00:00:00"
    assert data["started"] == "2021-01-01T00:00:00"
    assert data["finished"] == "2021-01-01T00:00:00"
    assert data["state"] == "FINISHED"
    assert data["progress"] == 1.0
    assert len(data["results"]) == 2
    assert data["results"][0]["sql"] == "SELECT 1 AS col"
    assert data["results"][0]["columns"] == [{"name": "col", "type": "STR"}]
    assert data["results"][0]["rows"] == [[1]]
    assert data["results"][1]["sql"] == "SELECT 2 AS another_col"
    assert data["results"][1]["columns"] == [{"name": "another_col", "type": "STR"}]
    assert data["results"][1]["rows"] == [[2]]
    assert data["errors"] == []


def test_submit_query_results_backend(
    session: Session,
    settings: Settings,
    client: TestClient,
) -> None:
    """
    Test that ``POST /queries/`` stores results.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col",
    )

    with freeze_time("2021-01-01T00:00:00Z"):
        response = client.post(
            "/queries/",
            data=query_create.json(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    data = response.json()

    cached = settings.results_backend.get(data["id"])
    assert json.loads(cached) == [
        {
            "sql": "SELECT 1 AS col",
            "columns": [{"name": "col", "type": "STR"}],
            "rows": [[1]],
            "row_count": 1,
        },
    ]


def test_submit_query_async(
    mocker: MockerFixture,
    session: Session,
    client: TestClient,
) -> None:
    """
    Test ``POST /queries/`` on an async database.
    """
    add_task = mocker.patch("fastapi.BackgroundTasks.add_task")

    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1 AS col",
        async_=True,
    )

    with freeze_time("2021-01-01T00:00:00Z", auto_tick_seconds=300):
        response = client.post(
            "/queries/",
            data=query_create.json(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    data = response.json()

    assert response.status_code == 201
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1 AS col"
    assert data["executed_query"] is None
    assert data["scheduled"] is None
    assert data["started"] is None
    assert data["finished"] is None
    assert data["state"] == "ACCEPTED"
    assert data["progress"] == 0.0
    assert data["results"] == []
    assert data["errors"] == []

    # check that ``BackgroundTasks.add_task`` was called
    add_task.assert_called()
    arguments = add_task.mock_calls[0].args
    assert arguments[0] == process_query  # pylint: disable=comparison-with-callable
    assert arguments[1] == session
    assert isinstance(arguments[2], Settings)
    assert isinstance(arguments[3], Query)


def test_submit_query_error(session: Session, client: TestClient) -> None:
    """
    Test submitting invalid query to ``POST /queries/``.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query_create = QueryCreate(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT FROM",
        async_=False,
    )

    response = client.post(
        "/queries/",
        data=query_create.json(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT FROM"
    assert data["executed_query"] == "SELECT FROM"
    assert data["state"] == "FAILED"
    assert data["progress"] == 0.0
    assert data["results"] == []
    assert data["errors"] == [
        '(sqlite3.OperationalError) near "FROM": syntax error\n'
        "[SQL: SELECT FROM]\n"
        "(Background on this error at: https://sqlalche.me/e/14/e3q8)",
    ]


def test_read_query(session: Session, settings: Settings, client: TestClient) -> None:
    """
    Test ``GET /queries/{query_id}``.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query = Query(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1",
        executed_query="SELECT 1",
        state=QueryState.RUNNING,
        progress=0.5,
        async_=False,
    )
    session.add(query)
    session.commit()
    session.refresh(query)

    results = Results(
        __root__=[
            StatementResults(
                sql="SELECT 1",
                columns=[{"name": "col", "type": "STR"}],
                rows=[[1]],
            ),
        ],
    )
    settings.results_backend.add(str(query.id), results.json())

    response = client.get(f"/queries/{query.id}")
    data = response.json()

    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1"
    assert data["executed_query"] == "SELECT 1"
    assert data["state"] == "RUNNING"
    assert data["progress"] == 0.5
    assert len(data["results"]) == 1
    assert data["results"][0]["sql"] == "SELECT 1"
    assert data["results"][0]["columns"] == [{"name": "col", "type": "STR"}]
    assert data["results"][0]["rows"] == [[1]]
    assert data["errors"] == []

    response = client.get("/queries/27289db6-a75c-47fc-b451-da59a743a168")
    assert response.status_code == 404

    response = client.get("/queries/123")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_read_query_no_results_backend(session: Session, client: TestClient) -> None:
    """
    Test ``GET /queries/{query_id}``.
    """
    engine = Engine(name="test_engine", version="1.0", uri="sqlite://")
    catalog = Catalog(name="test_catalog", engines=[engine])
    session.add(catalog)
    session.commit()
    session.refresh(catalog)

    query = Query(
        catalog_name=catalog.name,
        engine_name=engine.name,
        engine_version=engine.version,
        submitted_query="SELECT 1",
        executed_query="SELECT 1",
        state=QueryState.RUNNING,
        progress=0.5,
        async_=False,
    )
    session.add(query)
    session.commit()
    session.refresh(query)

    response = client.get(f"/queries/{query.id}")
    data = response.json()

    assert response.status_code == 200
    assert data["catalog_name"] == "test_catalog"
    assert data["engine_name"] == "test_engine"
    assert data["engine_version"] == "1.0"
    assert data["submitted_query"] == "SELECT 1"
    assert data["executed_query"] == "SELECT 1"
    assert data["state"] == "RUNNING"
    assert data["progress"] == 0.5
    assert data["results"] == []
    assert data["errors"] == []

    response = client.get("/queries/27289db6-a75c-47fc-b451-da59a743a168")
    assert response.status_code == 404

    response = client.get("/queries/123")
