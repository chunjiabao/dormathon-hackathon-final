"""Workspace A must never read or modify workspace B."""

from sqlalchemy import select

from app.models import ApiRequest


def test_settings_of_other_workspace_not_visible(client, owner_headers, other_app):
    res = client.get(f"/api/v1/settings/workspace?workspace_id={other_app.workspace_id}", headers=owner_headers)
    assert res.status_code == 404


def test_cannot_patch_other_workspace(client, owner_headers, other_app):
    res = client.patch(
        f"/api/v1/settings/workspace?workspace_id={other_app.workspace_id}",
        json={"monthly_budget_myr": 1},
        headers=owner_headers,
    )
    assert res.status_code == 404


def test_cannot_rotate_other_workspace_key(client, owner_headers, other_app):
    assert client.post(f"/api/v1/applications/{other_app.id}/rotate-key", headers=owner_headers).status_code == 404


def test_user_cannot_chat_with_other_workspace_app(client, owner_headers, other_app, mock_provider, session):
    res = client.post(
        "/api/v1/chat", json={"application_id": str(other_app.id), "message": "hello"}, headers=owner_headers
    )
    assert res.status_code == 404
    assert mock_provider.calls == 0
    assert session.scalars(select(ApiRequest)).all() == []


def test_chat_token_is_scoped_to_one_app(client, chat_headers, other_app, mock_provider):
    res = client.post(
        "/api/v1/chat", json={"application_id": str(other_app.id), "message": "hello"}, headers=chat_headers
    )
    assert res.status_code == 404
    assert mock_provider.calls == 0


def test_other_owner_sees_only_their_workspace(client, other_owner_headers, other_app):
    me = client.get("/api/v1/me", headers=other_owner_headers).json()
    assert [m["workspace_id"] for m in me["memberships"]] == [str(other_app.workspace_id)]
    res = client.get("/api/v1/settings/workspace", headers=other_owner_headers)
    assert res.json()["workspace_id"] == str(other_app.workspace_id)
