"""Keystone's v3 API, the parts core-api uses: tokens, users by federated identity, role assignments, projects."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from cloud_sim.api.errors import keystone_error
from cloud_sim.cloud import Cloud, NotFound, Project, User

router = APIRouter(prefix="/identity/v3")

# The federated identity provider and protocol users sign in through (OQ-F17-01).
IDP_ID = "smart-ticket"
PROTOCOL_ID = "openid"
MEMBER_ROLE = {"id": "member", "name": "member"}


@dataclass(frozen=True)
class Token:
    user: User
    expires_at: datetime


class Tokens:
    """The tokens Keystone has issued."""

    def __init__(self, cloud: Cloud, ttl_sec: int) -> None:
        self.cloud = cloud
        self.ttl = timedelta(seconds=ttl_sec)
        self._issued: dict[str, Token] = {}

    def issue(self, user: User) -> tuple[str, Token]:
        value = secrets.token_urlsafe(32)
        token = Token(user, self.cloud.now() + self.ttl)
        self._issued[value] = token
        return value, token

    def check(self, value: str | None) -> Token | None:
        """The live token with this value, if any."""
        token = self._issued.get(value or "")
        if token is None or token.expires_at <= self.cloud.now():
            return None
        return token


def cloud_of(request: Request) -> Cloud:
    cloud: Cloud = request.app.state.cloud
    return cloud


def admin(request: Request, x_auth_token: Annotated[str | None, Header()] = None) -> Token:
    """The caller's token, which must be a live system-scoped admin token."""
    token = request.app.state.tokens.check(x_auth_token)
    if token is None or not token.user.system_admin:
        raise keystone_error(401, "The request you have made requires authentication.")
    return token


Admin = Annotated[Token, Depends(admin)]


@router.post("/auth/tokens")
def issue_token(request: Request, body: dict[str, Any]) -> Response:
    auth = body.get("auth") or {}
    identity = auth.get("identity") or {}
    password = (identity.get("password") or {}).get("user") or {}
    if "password" not in (identity.get("methods") or []) or not (auth.get("scope") or {}).get(
        "system"
    ):
        raise keystone_error(401, "Only password authentication with system scope is supported.")
    user = cloud_of(request).authenticate(
        str(password.get("name", "")), str(password.get("password", ""))
    )
    if user is None:
        raise keystone_error(401, "The request you have made requires authentication.")
    value, token = request.app.state.tokens.issue(user)
    base = str(request.base_url).rstrip("/")
    catalog = [
        {
            "type": kind,
            "name": name,
            "endpoints": [
                {"interface": "public", "region": cloud_of(request).region, "url": f"{base}{path}"}
            ],
        }
        for kind, name, path in (
            ("identity", "keystone", "/identity/v3"),
            ("compute", "nova", "/compute/v2.1"),
            ("volumev3", "cinderv3", "/volume/v3"),
            ("network", "neutron", "/network"),
        )
    ]
    content = {
        "token": {
            "methods": ["password"],
            "user": {"id": user.id, "name": user.name, "domain": {"id": user.domain_id}},
            "system": {"all": True},
            "roles": [{"id": "admin", "name": "admin"}],
            "expires_at": token.expires_at.isoformat(),
            "catalog": catalog,
        }
    }
    return JSONResponse(content, status_code=201, headers={"X-Subject-Token": value})


@router.get("/users")
def list_users(
    request: Request,
    _: Admin,
    name: str | None = None,
    domain_id: str | None = None,
    idp_id: str | None = None,
    protocol_id: str | None = None,
    unique_id: str | None = None,
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        users = [u for u in cloud.users.values() if not u.system_admin]
        if name is not None:
            users = [u for u in users if u.name == name]
        if domain_id is not None:
            users = [u for u in users if u.domain_id == domain_id]
        if idp_id not in (None, IDP_ID) or protocol_id not in (None, PROTOCOL_ID):
            users = []
        if unique_id is not None:
            users = [u for u in users if u.subject == unique_id]
        return {"users": [user_view(u) for u in users]}


@router.get("/users/{user_id}")
def get_user(request: Request, user_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        try:
            return {"user": user_view(cloud.user(user_id))}
        except NotFound as e:
            raise keystone_error(404, str(e)) from None


@router.get("/role_assignments")
def role_assignments(
    request: Request,
    _: Admin,
    user_id: Annotated[str | None, Query(alias="user.id")] = None,
    project_id: Annotated[str | None, Query(alias="scope.project.id")] = None,
    include_names: bool = False,
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        rows = [
            (user, project)
            for user, projects in cloud.members.items()
            for project in projects
            if (user_id is None or user == user_id)
            and (project_id is None or project == project_id)
        ]
        assignments = []
        for user, project in rows:
            scope: dict[str, Any] = {"id": project}
            role: dict[str, Any] = dict(MEMBER_ROLE)
            who: dict[str, Any] = {"id": user}
            if include_names:
                scope["name"] = cloud.projects[project].name
                who["name"] = cloud.users[user].name
            assignments.append({"role": role, "user": who, "scope": {"project": scope}})
        return {"role_assignments": assignments}


@router.get("/projects")
def list_projects(
    request: Request, _: Admin, domain_id: str | None = None, name: str | None = None
) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        projects = [
            p
            for p in cloud.projects.values()
            if (domain_id is None or p.domain_id == domain_id) and (name is None or p.name == name)
        ]
        return {"projects": [project_view(p) for p in projects]}


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        try:
            return {"project": project_view(cloud.project(project_id))}
        except NotFound as e:
            raise keystone_error(404, str(e)) from None


@router.get("/domains")
def list_domains(request: Request, _: Admin) -> dict[str, Any]:
    cloud = cloud_of(request)
    with cloud.reading():
        return {
            "domains": [
                {"id": d.id, "name": d.name, "enabled": True} for d in cloud.domains.values()
            ]
        }


def user_view(user: User) -> dict[str, Any]:
    federated = (
        [{"idp_id": IDP_ID, "protocols": [{"protocol_id": PROTOCOL_ID, "unique_id": user.subject}]}]
        if user.subject
        else []
    )
    return {
        "id": user.id,
        "name": user.name,
        "domain_id": user.domain_id,
        "enabled": True,
        "federated": federated,
    }


def project_view(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "domain_id": project.domain_id,
        "enabled": True,
        "tags": [f"environment:{project.environment}"],
    }
