"""
Account endpoints, and sign-in (ADR-0029): `/api/auth/login` and
`/api/auth/refresh` answer with an access token and set the rotating refresh
token as an httpOnly cookie, one per frontend (`X-Auth-Client`).
"""

import uuid
from typing import Any, Literal, cast

from django.conf import settings
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Form, Header, Query, Router, Status
from ninja.errors import HttpError

from apps.accounts.models import (
    AccessReviewCampaign,
    AccessReviewItem,
    Assignment,
    AuthClient,
    Department,
    RefreshSession,
    Role,
    User,
)
from apps.accounts.permissions import AuthedRequest, SessionAuth, require
from apps.accounts.request_schema import (
    CampaignIn,
    DecideIn,
    DelegatedGrantIn,
    DepartmentIn,
    DepartmentMoveIn,
    DepartmentPatchIn,
    ExtendIn,
    GrantIn,
    ImportIn,
    LoginIn,
    OidcExchangeIn,
    PlaceIn,
    ProfileIn,
    ProvisionIn,
    ReasonIn,
    BaseRoleIn,
    RoleIn,
    RolePatchIn,
)
from apps.accounts.response_schema import (
    AccountOut,
    AssignmentOut,
    CampaignDetailOut,
    CampaignOut,
    DepartmentOut,
    ExplainOut,
    HolderOut,
    ImportOut,
    OidcConfigOut,
    PermissionOut,
    PersonAccessOut,
    PersonRecordOut,
    RefusedOut,
    ReviewItemOut,
    RoleOut,
    SessionOut,
    SignInOut,
    SourceOut,
    StaffOut,
    UserOut,
)
from apps.accounts.utils.access import Access, explained, holders, scope_names
from apps.accounts.utils.catalog import Permission, ScopeKind
from apps.accounts.utils.departments import DepartmentDraft, departments
from apps.accounts.utils.grants import GrantRequest, grants
from apps.accounts.utils.org_import import ImportResult, org_import
from apps.accounts.utils.people import Profile
from apps.accounts.utils.people import people as people_service
from apps.accounts.utils.reviews import CampaignRequest, access_reviews
from apps.accounts.utils.roles import RoleDraft, roles
from apps.accounts.utils import IssuedSession, Requester, SessionRefused, sessions
from apps.accounts.utils.rights import account_rights
from apps.accounts.utils.oidc import oidc_sign_in

router = Router(tags=["accounts"])
auth_router = Router(tags=["auth"])
access_router = Router(tags=["access"])
org_router = Router(tags=["org"])

PERSON_RELATIONS = ("department", "line_manager")

# The refresh cookie is sent only to the sign-in endpoints.
COOKIE_PATH = "/api/auth/"


@router.get("/me", auth=SessionAuth(), response=UserOut)
@require(Permission.SELF_PROFILE)
def me(request: AuthedRequest) -> User:
    return User.objects.select_related(*PERSON_RELATIONS).get(pk=request.auth.user.pk)


@router.get("/staff", auth=SessionAuth(), response=list[StaffOut])
@require(Permission.ACCESS_PEOPLE_READ)
def staff(request: AuthedRequest) -> QuerySet[User]:
    return User.objects.support_staff().order_by("username")


@router.get("/people", auth=SessionAuth(), response=list[AccountOut])
@require(Permission.ACCESS_PEOPLE_READ)
def people(request: AuthedRequest) -> QuerySet[User]:
    return (
        User.objects.select_related(*PERSON_RELATIONS)
        .prefetch_related("assignments__role", "team_memberships__team")
        .order_by("username")
    )


@router.put("/people/{username}/base-role", auth=SessionAuth(), response=AccountOut)
@require(Permission.ACCESS_GRANT)
def set_base_role(request: AuthedRequest, username: str, payload: BaseRoleIn) -> User:
    account_rights.set_base_role(request.auth.user, username, payload.role, payload.reason)
    return person(username)


@router.post("/people", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_MANAGE)
def provision_person(request: AuthedRequest, payload: ProvisionIn) -> User:
    user = people_service.provision(
        request.auth.user, payload.username, payload.email, profile_of(payload), payload.reason
    )
    return person(user.username)


@router.get("/people/{username}", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_READ)
def get_person(request: AuthedRequest, username: str) -> User:
    return person(username)


@router.patch("/people/{username}", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_MANAGE)
def update_person(request: AuthedRequest, username: str, payload: ProfileIn) -> User:
    people_service.update(request.auth.user, username, profile_of(payload), payload.reason)
    return person(username)


@router.post("/people/{username}/suspend", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_MANAGE)
def suspend_person(request: AuthedRequest, username: str, payload: ReasonIn) -> User:
    people_service.suspend(request.auth.user, username, payload.reason)
    return person(username)


@router.post("/people/{username}/reactivate", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_MANAGE)
def reactivate_person(request: AuthedRequest, username: str, payload: ReasonIn) -> User:
    people_service.reactivate(request.auth.user, username, payload.reason)
    return person(username)


@router.post("/people/{username}/deactivate", auth=SessionAuth(), response=PersonRecordOut)
@require(Permission.ACCESS_PEOPLE_MANAGE)
def deactivate_person(request: AuthedRequest, username: str, payload: ReasonIn) -> User:
    people_service.deactivate(request.auth.user, username, payload.reason)
    return person(username)


def person(username: str) -> User:
    found = (
        User.objects.select_related(*PERSON_RELATIONS)
        .prefetch_related("assignments__role", "team_memberships__team")
        .filter(username=username)
        .first()
    )
    if found is None:
        raise HttpError(404, "person not found")
    return found


def profile_of(payload: ProfileIn) -> Profile:
    return Profile(
        first_name=payload.first_name,
        last_name=payload.last_name,
        job_title=payload.job_title,
        location=payload.location,
        phone=payload.phone,
        employee_id=payload.employee_id,
        department=payload.department,
        line_manager=payload.line_manager,
    )


# ── /api/access: permissions, roles, grants, explanations, reviews (F14) ──


@access_router.get("/permissions", auth=SessionAuth(), response=list[PermissionOut])
@require(Permission.ACCESS_READ)
def list_permissions(request: AuthedRequest) -> list[PermissionOut]:
    return [PermissionOut.of(p) for p in sorted(Permission, key=lambda p: p.value)]


@access_router.get("/roles", auth=SessionAuth(), response=list[RoleOut])
@require(Permission.ACCESS_READ)
def list_roles(request: AuthedRequest, include_retired: bool = False) -> list[RoleOut]:
    rows = Role.objects.annotate(
        live=Count(
            "assignments",
            filter=Q(assignments__ended_at__isnull=True, assignments__user__is_active=True),
        )
    ).order_by("-is_system", "name")
    if not include_retired:
        rows = rows.filter(retired_at__isnull=True)
    return [RoleOut.of(role, role.live) for role in rows]


@access_router.post("/roles", auth=SessionAuth(), response=RoleOut)
@require(Permission.ACCESS_ROLES_MANAGE)
def create_role(request: AuthedRequest, payload: RoleIn) -> RoleOut:
    role = roles.create(
        request.auth.user,
        RoleDraft(
            payload.name,
            payload.description,
            payload.permissions,
            payload.reason,
            payload.delegable,
        ),
    )
    return RoleOut.of(role)


@access_router.get("/roles/{urn}", auth=SessionAuth(), response=RoleOut)
@require(Permission.ACCESS_READ)
def get_role(request: AuthedRequest, urn: str) -> RoleOut:
    role = Role.objects.filter(urn=urn).first()
    if role is None:
        raise HttpError(404, "role not found")
    return RoleOut.of(role, Assignment.objects.active().filter(role=role).count())


@access_router.patch("/roles/{urn}", auth=SessionAuth(), response=RoleOut)
@require(Permission.ACCESS_ROLES_MANAGE)
def update_role(request: AuthedRequest, urn: str, payload: RolePatchIn) -> RoleOut:
    role = roles.update(
        request.auth.user,
        urn,
        RoleDraft(
            payload.name,
            payload.description,
            payload.permissions,
            payload.reason,
            payload.delegable,
        ),
    )
    return RoleOut.of(role, Assignment.objects.active().filter(role=role).count())


@access_router.post("/roles/{urn}/retire", auth=SessionAuth(), response=RoleOut)
@require(Permission.ACCESS_ROLES_MANAGE)
def retire_role(request: AuthedRequest, urn: str, payload: ReasonIn) -> RoleOut:
    return RoleOut.of(roles.retire(request.auth.user, urn, payload.reason))


@access_router.get(
    "/people/{username}/assignments", auth=SessionAuth(), response=list[AssignmentOut]
)
@require(Permission.ACCESS_READ)
def list_assignments(
    request: AuthedRequest, username: str, include_ended: bool = False
) -> list[AssignmentOut]:
    rows = Assignment.objects.filter(user__username=username)
    if not include_ended:
        rows = rows.filter(ended_at__isnull=True)
    now = timezone.now()
    return [
        AssignmentOut.of(row, now)
        for row in rows.select_related(
            "user", "role", "granted_by", "scope_team", "scope_department"
        ).order_by("-starts_at")
    ]


@access_router.post("/people/{username}/assignments", auth=SessionAuth(), response=AssignmentOut)
@require(Permission.ACCESS_GRANT)
def grant(request: AuthedRequest, username: str, payload: GrantIn) -> AssignmentOut:
    row = grants.grant(
        request.auth.user,
        GrantRequest(
            username=username,
            role_urn=payload.role,
            scope_kind=payload.scope_kind,
            scope_ref=payload.scope,
            reason=payload.reason,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
        ),
    )
    return AssignmentOut.of(row, timezone.now())


@access_router.post("/assignments/{assignment_id}/end", auth=SessionAuth(), response=AssignmentOut)
@require(Permission.ACCESS_GRANT)
def end_assignment(
    request: AuthedRequest, assignment_id: uuid.UUID, payload: ReasonIn
) -> AssignmentOut:
    return AssignmentOut.of(
        grants.end(request.auth.user, assignment_id, payload.reason), timezone.now()
    )


@access_router.post(
    "/assignments/{assignment_id}/extend", auth=SessionAuth(), response=AssignmentOut
)
@require(Permission.ACCESS_GRANT)
def extend_assignment(
    request: AuthedRequest, assignment_id: uuid.UUID, payload: ExtendIn
) -> AssignmentOut:
    row = grants.extend(request.auth.user, assignment_id, payload.ends_at, payload.reason)
    return AssignmentOut.of(row, timezone.now())


@access_router.post(
    "/assignments/{assignment_id}/confirm", auth=SessionAuth(), response=AssignmentOut
)
@require(Permission.ACCESS_GRANT)
def confirm_assignment(
    request: AuthedRequest, assignment_id: uuid.UUID, payload: ReasonIn
) -> AssignmentOut:
    row = grants.confirm(request.auth.user, assignment_id, payload.reason)
    return AssignmentOut.of(row, timezone.now())


@access_router.get("/me", auth=SessionAuth(), response=PersonAccessOut)
@require(Permission.SELF_PROFILE)
def my_access(request: AuthedRequest) -> dict[str, Any]:
    return {
        "username": request.auth.user.username,
        "role": request.auth.user.role,
        "permissions": explained(request.auth.user),
    }


@access_router.get("/people/{username}/access", auth=SessionAuth(), response=PersonAccessOut)
@require(Permission.ACCESS_READ)
def person_access(request: AuthedRequest, username: str) -> dict[str, Any]:
    user = person(username)
    return {"username": user.username, "role": user.role, "permissions": explained(user)}


@access_router.get("/people/{username}/explain", auth=SessionAuth(), response=ExplainOut)
@require(Permission.ACCESS_READ)
def explain(request: AuthedRequest, username: str, permission: Permission) -> dict[str, Any]:
    user = person(username)
    access = Access.of(user)
    scope = access.scope(permission)
    return {
        "username": user.username,
        "permission": permission.value,
        "holds": scope is not None,
        "scope": scope_names(scope) if scope else None,
        "sources": [SourceOut.of(s) for s in access.sources.get(permission, [])],
    }


@access_router.get("/holders", auth=SessionAuth(), response=list[HolderOut])
@require(Permission.ACCESS_READ)
def permission_holders(request: AuthedRequest, permission: Permission) -> list[HolderOut]:
    return [
        HolderOut(
            username=user.username,
            name=user.get_full_name(),
            role=user.role,
            sources=[SourceOut.of(s) for s in sources],
        )
        for user, sources in holders(permission)
    ]


@access_router.get("/reviews", auth=SessionAuth(), response=list[CampaignOut])
@require(Permission.ACCESS_REVIEW_MANAGE)
def list_reviews(request: AuthedRequest) -> list[CampaignOut]:
    rows = AccessReviewCampaign.objects.select_related(
        "role", "department", "fallback_reviewer", "created_by"
    ).order_by("-opened_at")
    return [CampaignOut.of(c, access_reviews.summary(c)) for c in rows]


@access_router.post("/reviews", auth=SessionAuth(), response=CampaignOut)
@require(Permission.ACCESS_REVIEW_MANAGE)
def open_review(request: AuthedRequest, payload: CampaignIn) -> CampaignOut:
    campaign = access_reviews.open(
        request.auth.user,
        CampaignRequest(
            name=payload.name,
            fallback_reviewer=payload.fallback_reviewer,
            on_no_answer=payload.on_no_answer,
            role_urn=payload.role,
            department=payload.department,
            closes_at=payload.closes_at,
        ),
    )
    return CampaignOut.of(campaign, access_reviews.summary(campaign))


@access_router.get("/reviews/inbox", auth=SessionAuth(), response=list[ReviewItemOut])
@require(Permission.ACCESS_REVIEW_RESPOND)
def review_inbox(request: AuthedRequest) -> list[ReviewItemOut]:
    rows = (
        review_items().filter(reviewer=request.auth.user).pending().order_by("campaign__closes_at")
    )
    return [ReviewItemOut.of(item) for item in rows]


@access_router.get("/reviews/{campaign_id}", auth=SessionAuth(), response=CampaignDetailOut)
@require(Permission.ACCESS_REVIEW_MANAGE)
def get_review(request: AuthedRequest, campaign_id: uuid.UUID) -> CampaignDetailOut:
    campaign = (
        AccessReviewCampaign.objects.select_related(
            "role", "department", "fallback_reviewer", "created_by"
        )
        .filter(pk=campaign_id)
        .first()
    )
    if campaign is None:
        raise HttpError(404, "review not found")
    base = CampaignOut.of(campaign, access_reviews.summary(campaign))
    items = review_items().filter(campaign=campaign).order_by("assignment__user__username")
    return CampaignDetailOut(**base.model_dump(), items=[ReviewItemOut.of(i) for i in items])


@access_router.post("/reviews/{campaign_id}/close", auth=SessionAuth(), response=CampaignOut)
@require(Permission.ACCESS_REVIEW_MANAGE)
def close_review(request: AuthedRequest, campaign_id: uuid.UUID) -> CampaignOut:
    campaign = access_reviews.close(request.auth.user, campaign_id)
    return CampaignOut.of(campaign, access_reviews.summary(campaign))


@access_router.post("/reviews/items/{item_id}/decide", auth=SessionAuth(), response=ReviewItemOut)
@require(Permission.ACCESS_REVIEW_RESPOND)
def decide_review_item(
    request: AuthedRequest, item_id: uuid.UUID, payload: DecideIn
) -> ReviewItemOut:
    access_reviews.decide(request.auth.user, item_id, payload.decision, payload.note)
    return ReviewItemOut.of(review_items().get(pk=item_id))


def review_items() -> Any:
    return AccessReviewItem.objects.select_related(
        "campaign",
        "reviewer",
        "assignment__user",
        "assignment__role",
        "assignment__granted_by",
        "assignment__scope_team",
        "assignment__scope_department",
    )


# ── /api/org: departments and imports (F14) ──


@org_router.get("/departments", auth=SessionAuth(), response=list[DepartmentOut])
@require(Permission.ORG_DEPARTMENTS_READ)
def list_departments(request: AuthedRequest, include_archived: bool = False) -> list[DepartmentOut]:
    rows = Department.objects.select_related("parent", "head").annotate(
        members=Count("people", filter=Q(people__is_active=True))
    )
    if not include_archived:
        rows = rows.filter(archived_at__isnull=True)
    return [DepartmentOut.of(d, d.members) for d in rows.order_by("code")]


@org_router.post("/departments", auth=SessionAuth(), response=DepartmentOut)
@require(Permission.ORG_DEPARTMENTS_MANAGE)
def create_department(request: AuthedRequest, payload: DepartmentIn) -> DepartmentOut:
    department = departments.create(
        request.auth.user,
        payload.code,
        DepartmentDraft(payload.name, payload.parent, payload.head, payload.cost_centre),
        payload.reason,
    )
    return department_out(department.code)


@org_router.get("/departments/{code}", auth=SessionAuth(), response=DepartmentOut)
@require(Permission.ORG_DEPARTMENTS_READ)
def get_department(request: AuthedRequest, code: str) -> DepartmentOut:
    return department_out(code)


@org_router.get("/departments/{code}/people", auth=SessionAuth(), response=list[AccountOut])
@require(Permission.ORG_DEPARTMENTS_READ)
def department_people(request: AuthedRequest, code: str) -> QuerySet[User]:
    department = departments.live(code)
    if not Access.of(request.auth.user).holds(Permission.ACCESS_PEOPLE_READ):
        departments.check_reach(request.auth.user, department)
    return (
        User.objects.filter(department=department)
        .select_related(*PERSON_RELATIONS)
        .prefetch_related("assignments__role", "team_memberships__team")
        .order_by("username")
    )


@org_router.post("/departments/{code}/people", auth=SessionAuth(), response=AccountOut)
@require(Permission.ORG_DEPARTMENTS_MANAGE)
def place_in_department(request: AuthedRequest, code: str, payload: PlaceIn) -> User:
    user = departments.move_person(request.auth.user, code, payload.username, payload.reason)
    return person(user.username)


@org_router.get("/delegable-roles", auth=SessionAuth(), response=list[RoleOut])
@require(Permission.ACCESS_GRANT_DELEGABLE)
def delegable_roles(request: AuthedRequest) -> list[RoleOut]:
    rows = (
        Role.objects.filter(is_system=False, delegable=True, retired_at__isnull=True)
        .annotate(
            live=Count(
                "assignments",
                filter=Q(assignments__ended_at__isnull=True, assignments__user__is_active=True),
            )
        )
        .order_by("name")
    )
    return [RoleOut.of(role, role.live) for role in rows]


@org_router.get("/departments/{code}/grants", auth=SessionAuth(), response=list[AssignmentOut])
@require(Permission.ORG_DEPARTMENTS_READ)
def department_grants(request: AuthedRequest, code: str) -> list[AssignmentOut]:
    department = departments.live(code)
    if not Access.of(request.auth.user).holds(Permission.ACCESS_READ):
        departments.check_reach(request.auth.user, department)
    now = timezone.now()
    rows = (
        Assignment.objects.active(now)
        .filter(scope_department_id__in=departments.subtree_ids(department))
        .select_related("user", "role", "granted_by", "scope_team", "scope_department")
        .order_by("user__username")
    )
    return [AssignmentOut.of(row, now) for row in rows]


@org_router.post("/departments/{code}/grants", auth=SessionAuth(), response=AssignmentOut)
@require(Permission.ACCESS_GRANT_DELEGABLE)
def delegate_grant(request: AuthedRequest, code: str, payload: DelegatedGrantIn) -> AssignmentOut:
    row = grants.grant(
        request.auth.user,
        GrantRequest(
            username=payload.username,
            role_urn=payload.role,
            scope_kind=ScopeKind.DEPARTMENT,
            scope_ref=code,
            reason=payload.reason,
            starts_at=None,
            ends_at=payload.ends_at,
        ),
        delegated=True,
    )
    return AssignmentOut.of(row, timezone.now())


@org_router.post(
    "/departments/{code}/grants/{assignment_id}/end", auth=SessionAuth(), response=AssignmentOut
)
@require(Permission.ACCESS_GRANT_DELEGABLE)
def end_delegated_grant(
    request: AuthedRequest, code: str, assignment_id: uuid.UUID, payload: ReasonIn
) -> AssignmentOut:
    row = grants.end(request.auth.user, assignment_id, payload.reason, delegated=True)
    return AssignmentOut.of(row, timezone.now())


@org_router.patch("/departments/{code}", auth=SessionAuth(), response=DepartmentOut)
@require(Permission.ORG_DEPARTMENTS_MANAGE)
def update_department(
    request: AuthedRequest, code: str, payload: DepartmentPatchIn
) -> DepartmentOut:
    department = departments.update(
        request.auth.user,
        code,
        DepartmentDraft(name=payload.name, head=payload.head, cost_centre=payload.cost_centre),
        payload.reason,
    )
    return department_out(department.code)


@org_router.post("/departments/{code}/move", auth=SessionAuth(), response=DepartmentOut)
@require(Permission.ORG_DEPARTMENTS_MANAGE)
def move_department(request: AuthedRequest, code: str, payload: DepartmentMoveIn) -> DepartmentOut:
    department = departments.move(request.auth.user, code, payload.parent, payload.reason)
    return department_out(department.code)


@org_router.post("/departments/{code}/archive", auth=SessionAuth(), response=DepartmentOut)
@require(Permission.ORG_DEPARTMENTS_MANAGE)
def archive_department(request: AuthedRequest, code: str, payload: ReasonIn) -> DepartmentOut:
    department = departments.archive(request.auth.user, code, payload.reason)
    return department_out(department.code)


@org_router.post("/import/departments", auth=SessionAuth(), response=ImportOut)
@require(Permission.ORG_IMPORT)
def import_departments(
    request: AuthedRequest, payload: ImportIn, dry_run: bool = Query(True)
) -> dict[str, Any]:
    result = org_import.departments(request.auth.user, payload.csv, payload.reason, dry_run=dry_run)
    return import_out(result, dry_run)


@org_router.post("/import/people", auth=SessionAuth(), response=ImportOut)
@require(Permission.ORG_IMPORT)
def import_people(
    request: AuthedRequest, payload: ImportIn, dry_run: bool = Query(True)
) -> dict[str, Any]:
    result = org_import.people(request.auth.user, payload.csv, payload.reason, dry_run=dry_run)
    return import_out(result, dry_run)


def department_out(code: str) -> DepartmentOut:
    department = (
        Department.objects.select_related("parent", "head").filter(code=code.upper()).first()
    )
    if department is None:
        raise HttpError(404, "department not found")
    return DepartmentOut.of(department, department.people.filter(is_active=True).count())


def import_out(result: ImportResult, dry_run: bool) -> dict[str, Any]:
    return {"applied": result.applied, "dry_run": dry_run, "rows": [vars(r) for r in result.rows]}


@auth_router.post("/login", auth=None, response={200: SessionOut, 401: RefusedOut})
def login(
    request: HttpRequest,
    response: HttpResponse,
    payload: LoginIn,
    x_auth_client: AuthClient = Header(...),
) -> Status[IssuedSession | RefusedOut]:
    try:
        issued = sessions.login(
            payload.username, payload.password, x_auth_client, requester(request)
        )
    except SessionRefused as e:
        return Status(401, RefusedOut(detail=str(e)))
    set_refresh_cookie(response, x_auth_client, issued)
    return Status(200, issued)


@auth_router.get("/oidc/config", auth=None, response=OidcConfigOut)
def oidc_config(request: HttpRequest) -> dict[str, str]:
    return oidc_sign_in.config()


@auth_router.post("/oidc/exchange", auth=None, response=SessionOut)
def oidc_exchange(
    request: HttpRequest,
    response: HttpResponse,
    payload: OidcExchangeIn,
    x_auth_client: AuthClient = Header(...),
) -> IssuedSession:
    issued = oidc_sign_in.exchange(
        code=payload.code,
        verifier=payload.code_verifier,
        nonce=payload.nonce,
        redirect_uri=payload.redirect_uri,
        client=x_auth_client,
        requester=requester(request),
    )
    set_refresh_cookie(response, x_auth_client, issued)
    return issued


@auth_router.post("/oidc/backchannel-logout", auth=None, response={200: None})
def oidc_backchannel_logout(request: HttpRequest, logout_token: Form[str]) -> Status[None]:
    oidc_sign_in.backchannel_logout(logout_token)
    return Status(200, None)


@auth_router.post("/refresh", auth=None, response={200: SessionOut, 401: RefusedOut})
def refresh(
    request: HttpRequest, response: HttpResponse, x_auth_client: AuthClient = Header(...)
) -> Status[IssuedSession | RefusedOut]:
    raw = request.COOKIES.get(cookie_name(x_auth_client))
    try:
        if not raw:
            raise SessionRefused("no refresh token")
        issued = sessions.refresh(raw, x_auth_client, requester(request))
    except SessionRefused as e:
        response.delete_cookie(cookie_name(x_auth_client), path=COOKIE_PATH)
        return Status(401, RefusedOut(detail=str(e)))
    set_refresh_cookie(response, x_auth_client, issued)
    return Status(200, issued)


@auth_router.post("/logout", auth=None, response={204: None})
def logout(
    request: HttpRequest, response: HttpResponse, x_auth_client: AuthClient = Header(...)
) -> Status[None]:
    raw = request.COOKIES.get(cookie_name(x_auth_client))
    if raw:
        sessions.logout(raw, x_auth_client)
    response.delete_cookie(cookie_name(x_auth_client), path=COOKIE_PATH)
    return Status(204, None)


@auth_router.get("/sessions", auth=SessionAuth(), response=list[SignInOut])
@require(Permission.SELF_SESSIONS)
def list_sign_ins(request: AuthedRequest) -> list[RefreshSession]:
    return sessions.live(request.auth.user)


@auth_router.delete("/sessions/{family}", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_SESSIONS)
def end_sign_in(request: AuthedRequest, family: uuid.UUID) -> Status[None]:
    sessions.end(request.auth.user, family)
    return Status(204, None)


@auth_router.post("/logout-everywhere", auth=SessionAuth(), response={204: None})
@require(Permission.SELF_SESSIONS)
def logout_everywhere(request: AuthedRequest, response: HttpResponse) -> Status[None]:
    sessions.end_all(request.auth.user)
    for client in AuthClient:
        response.delete_cookie(cookie_name(client), path=COOKIE_PATH)
    return Status(204, None)


def cookie_name(client: AuthClient) -> str:
    return f"st_refresh_{client.value}"


def set_refresh_cookie(response: HttpResponse, client: AuthClient, issued: IssuedSession) -> None:
    """Hands the browser the new refresh token, readable by no script."""
    if issued.refresh is None or issued.refresh_expires_at is None:
        return
    response.set_cookie(
        cookie_name(client),
        issued.refresh,
        expires=issued.refresh_expires_at,
        path=COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=cast(Literal["Lax", "Strict", "None"], settings.AUTH_COOKIE_SAMESITE),
    )


def requester(request: HttpRequest) -> Requester:
    return Requester(
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        ip_address=request.META.get("REMOTE_ADDR") or None,
    )
