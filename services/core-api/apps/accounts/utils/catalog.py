"""The permission catalogue and the system roles built from it (ADR-0045)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from apps.accounts.models import Capability, UserRole

NID = "smart-ticket"
PERMISSION_PREFIX = f"urn:{NID}:perm:"
ROLE_PREFIX = f"urn:{NID}:role:"
PERMISSION_URN = re.compile(
    r"^urn:smart-ticket:perm:[a-z][a-z0-9-]{0,31}(:[a-z][a-z0-9-]{0,31}){1,2}$"
)
ROLE_URN = re.compile(r"^urn:smart-ticket:role:(system|custom):[a-z][a-z0-9-]{1,47}$")
ROLE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,47}$")


class Permission(StrEnum):
    """Every action core-api gates, named by URN (BR-F14-20)."""

    ACCESS_GRANT = "urn:smart-ticket:perm:access:grant"
    ACCESS_GRANT_DELEGABLE = "urn:smart-ticket:perm:access:grant:delegable"
    ACCESS_PEOPLE_MANAGE = "urn:smart-ticket:perm:access:people:manage"
    ACCESS_PEOPLE_READ = "urn:smart-ticket:perm:access:people:read"
    ACCESS_READ = "urn:smart-ticket:perm:access:read"
    ACCESS_REVIEW_MANAGE = "urn:smart-ticket:perm:access:review:manage"
    ACCESS_REVIEW_RESPOND = "urn:smart-ticket:perm:access:review:respond"
    ACCESS_ROLES_MANAGE = "urn:smart-ticket:perm:access:roles:manage"
    INCIDENTS_MANAGE = "urn:smart-ticket:perm:incidents:manage"
    INCIDENTS_READ = "urn:smart-ticket:perm:incidents:read"
    INCIDENTS_UNLINK = "urn:smart-ticket:perm:incidents:unlink"
    KB_AUTHORITY_LOG_READ = "urn:smart-ticket:perm:kb:authority-log:read"
    KB_AUTHORITY_GRANT = "urn:smart-ticket:perm:kb:authority:grant"
    KB_AUTHORITY_QUEUE = "urn:smart-ticket:perm:kb:authority:queue"
    KB_AUTHORITY_RISK_TIER = "urn:smart-ticket:perm:kb:authority:risk-tier"
    KB_DRAFTS_MANAGE = "urn:smart-ticket:perm:kb:drafts:manage"
    KB_DRAFTS_WITHDRAW_ANY = "urn:smart-ticket:perm:kb:drafts:withdraw-any"
    KB_GAPS_MANAGE = "urn:smart-ticket:perm:kb:gaps:manage"
    KB_GRAPH_EDIT = "urn:smart-ticket:perm:kb:graph:edit"
    KB_GRAPH_READ = "urn:smart-ticket:perm:kb:graph:read"
    KB_GRAPH_REBUILD = "urn:smart-ticket:perm:kb:graph:rebuild"
    KB_PAGES_CREATE = "urn:smart-ticket:perm:kb:pages:create"
    KB_PAGES_READ = "urn:smart-ticket:perm:kb:pages:read"
    KB_PAGES_REINGEST = "urn:smart-ticket:perm:kb:pages:reingest"
    NOTIFICATIONS_DELIVERIES_MANAGE = "urn:smart-ticket:perm:notifications:deliveries:manage"
    NOTIFICATIONS_MATRIX_MANAGE = "urn:smart-ticket:perm:notifications:matrix:manage"
    NOTIFICATIONS_MATRIX_READ = "urn:smart-ticket:perm:notifications:matrix:read"
    NOTIFICATIONS_TEMPLATES_MANAGE = "urn:smart-ticket:perm:notifications:templates:manage"
    NOTIFICATIONS_WEBHOOKS_MANAGE = "urn:smart-ticket:perm:notifications:webhooks:manage"
    ORG_DEPARTMENTS_MANAGE = "urn:smart-ticket:perm:org:departments:manage"
    ORG_DEPARTMENTS_READ = "urn:smart-ticket:perm:org:departments:read"
    ORG_IMPORT = "urn:smart-ticket:perm:org:import"
    PII_ACCESS_LOG_READ = "urn:smart-ticket:perm:pii:access-log:read"
    PII_REVEAL = "urn:smart-ticket:perm:pii:reveal"
    PII_REVEAL_ANY = "urn:smart-ticket:perm:pii:reveal:any"
    REPORTS_DASHBOARD_READ = "urn:smart-ticket:perm:reports:dashboard:read"
    REPORTS_INCIDENTS_READ = "urn:smart-ticket:perm:reports:incidents:read"
    REPORTS_KB_READ = "urn:smart-ticket:perm:reports:kb:read"
    REPORTS_NOTIFICATIONS_READ = "urn:smart-ticket:perm:reports:notifications:read"
    REPORTS_OPERATIONS_READ = "urn:smart-ticket:perm:reports:operations:read"
    REPORTS_REVIEWERS_ALL = "urn:smart-ticket:perm:reports:reviewers:all"
    REPORTS_ROLLOUT_READ = "urn:smart-ticket:perm:reports:rollout:read"
    REPORTS_SECURITY_READ = "urn:smart-ticket:perm:reports:security:read"
    REPORTS_SECURITY_DETAIL = "urn:smart-ticket:perm:reports:security:detail"
    REPORTS_TEAMS_READ = "urn:smart-ticket:perm:reports:teams:read"
    REQUESTER_CHAT = "urn:smart-ticket:perm:requester:chat"
    REQUESTER_DEPARTMENT_READ = "urn:smart-ticket:perm:requester:department:read"
    REQUESTER_SUBMIT = "urn:smart-ticket:perm:requester:submit"
    REQUESTER_TICKET_STATUS = "urn:smart-ticket:perm:requester:ticket-status"
    REQUESTER_TICKETS = "urn:smart-ticket:perm:requester:tickets"
    REVIEW_FEWSHOT_READ = "urn:smart-ticket:perm:review:fewshot:read"
    REVIEW_QUEUE_WORK = "urn:smart-ticket:perm:review:queue:work"
    ROLLOUT_FLAG_OFF = "urn:smart-ticket:perm:rollout:flag:off"
    ROLLOUT_FLAG_ON = "urn:smart-ticket:perm:rollout:flag:on"
    ROLLOUT_GATES_MANAGE = "urn:smart-ticket:perm:rollout:gates:manage"
    ROLLOUT_READ = "urn:smart-ticket:perm:rollout:read"
    ROLLOUT_THRESHOLDS_READ = "urn:smart-ticket:perm:rollout:thresholds:read"
    RUNBOOKS_CATALOG_ACTIVATE = "urn:smart-ticket:perm:runbooks:catalog:activate"
    RUNBOOKS_CATALOG_MANAGE = "urn:smart-ticket:perm:runbooks:catalog:manage"
    RUNBOOKS_CATALOG_READ = "urn:smart-ticket:perm:runbooks:catalog:read"
    RUNBOOKS_EXECUTE = "urn:smart-ticket:perm:runbooks:execute"
    SECURITY_QUEUE_WORK = "urn:smart-ticket:perm:security:queue:work"
    SECURITY_SUMMARY_READ = "urn:smart-ticket:perm:security:summary:read"
    SELF_NOTIFICATIONS = "urn:smart-ticket:perm:self:notifications"
    SELF_PROFILE = "urn:smart-ticket:perm:self:profile"
    SELF_SESSIONS = "urn:smart-ticket:perm:self:sessions"
    SLA_MANAGE = "urn:smart-ticket:perm:sla:manage"
    SLA_POLICIES_ACTIVATE = "urn:smart-ticket:perm:sla:policies:activate"
    SLA_READ = "urn:smart-ticket:perm:sla:read"
    TEAMS_AVAILABILITY_MANAGE = "urn:smart-ticket:perm:teams:availability:manage"
    TEAMS_AVAILABILITY_OWN = "urn:smart-ticket:perm:teams:availability:own"
    TEAMS_LEAD = "urn:smart-ticket:perm:teams:lead"
    TEAMS_MANAGE = "urn:smart-ticket:perm:teams:manage"
    TEAMS_READ = "urn:smart-ticket:perm:teams:read"
    TEAMS_SUPERVISE = "urn:smart-ticket:perm:teams:supervise"
    TICKETS_ALL_CATEGORIES = "urn:smart-ticket:perm:tickets:all-categories"
    TICKETS_COMMENT = "urn:smart-ticket:perm:tickets:comment"
    TICKETS_FIELDS_WRITE = "urn:smart-ticket:perm:tickets:fields:write"
    TICKETS_LIFECYCLE_READ = "urn:smart-ticket:perm:tickets:lifecycle:read"
    TICKETS_MOVE = "urn:smart-ticket:perm:tickets:move"
    TICKETS_MOVE_FORCE = "urn:smart-ticket:perm:tickets:move:force"
    TICKETS_PRIORITY = "urn:smart-ticket:perm:tickets:priority"
    TICKETS_READ = "urn:smart-ticket:perm:tickets:read"
    TICKETS_REASSIGN = "urn:smart-ticket:perm:tickets:reassign"
    TICKETS_SLA_REBUILD = "urn:smart-ticket:perm:tickets:sla:rebuild"
    TICKETS_TAKE = "urn:smart-ticket:perm:tickets:take"
    TICKETS_TRANSFERS_RETRY = "urn:smart-ticket:perm:tickets:transfers:retry"
    TICKETS_WORKFLOW_CHANGE = "urn:smart-ticket:perm:tickets:workflow:change"
    WORKFLOWS_MANAGE = "urn:smart-ticket:perm:workflows:manage"
    WORKFLOWS_READ = "urn:smart-ticket:perm:workflows:read"


class ScopeKind(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    DEPARTMENT = "department"


@dataclass(frozen=True)
class PermissionSpec:
    """What a permission is, for the console's catalogue and the grant rules."""

    label: str
    staff_only: bool
    locked: bool
    scopes: tuple[ScopeKind, ...]


def _spec(
    label: str, *, staff_only: bool = True, locked: bool = False, scopes: tuple[str, ...] = ()
) -> PermissionSpec:
    return PermissionSpec(
        label, staff_only, locked, (ScopeKind.GLOBAL, *(ScopeKind(s) for s in scopes))
    )


P = Permission
PERMISSIONS: dict[Permission, PermissionSpec] = {
    P.ACCESS_GRANT: _spec("Set a person's base role and grant roles", locked=True),
    P.ACCESS_GRANT_DELEGABLE: _spec(
        "Grant delegable custom roles to people in the departments you head",
        locked=True,
        scopes=("department",),
    ),
    P.ACCESS_PEOPLE_MANAGE: _spec(
        "Pre-provision, suspend, reactivate and deactivate people", locked=True
    ),
    P.ACCESS_PEOPLE_READ: _spec("List people and their access"),
    P.ACCESS_READ: _spec("Read roles, grants and access explanations"),
    P.ACCESS_REVIEW_MANAGE: _spec("Open and close access reviews", locked=True),
    P.ACCESS_REVIEW_RESPOND: _spec("Answer the access reviews assigned to you"),
    P.ACCESS_ROLES_MANAGE: _spec("Create, change and retire custom roles", locked=True),
    P.INCIDENTS_MANAGE: _spec("Declare, confirm, broadcast, resolve and link incidents"),
    P.INCIDENTS_READ: _spec("Read incidents"),
    P.INCIDENTS_UNLINK: _spec("Unlink a ticket from an incident"),
    P.KB_AUTHORITY_LOG_READ: _spec("Read the authority log"),
    P.KB_AUTHORITY_GRANT: _spec("Allow or revoke automatic answers from a page", locked=True),
    P.KB_AUTHORITY_QUEUE: _spec("Read the authority queue"),
    P.KB_AUTHORITY_RISK_TIER: _spec("Change a page's risk tier", locked=True),
    P.KB_DRAFTS_MANAGE: _spec("Write, review and withdraw page drafts"),
    P.KB_DRAFTS_WITHDRAW_ANY: _spec("Withdraw anyone's page draft"),
    P.KB_GAPS_MANAGE: _spec("Read and dismiss knowledge gaps"),
    P.KB_GRAPH_EDIT: _spec("Correct a page's graph"),
    P.KB_GRAPH_READ: _spec("Read a page's graph"),
    P.KB_GRAPH_REBUILD: _spec("Ask for a page's graph to be rebuilt"),
    P.KB_PAGES_CREATE: _spec("Create a help page"),
    P.KB_PAGES_READ: _spec("Read the help pages", staff_only=False),
    P.KB_PAGES_REINGEST: _spec("Re-ingest a help page"),
    P.NOTIFICATIONS_DELIVERIES_MANAGE: _spec("Read and retry deliveries"),
    P.NOTIFICATIONS_MATRIX_MANAGE: _spec("Change the notification matrix"),
    P.NOTIFICATIONS_MATRIX_READ: _spec("Read the notification matrix"),
    P.NOTIFICATIONS_TEMPLATES_MANAGE: _spec("Change notification templates"),
    P.NOTIFICATIONS_WEBHOOKS_MANAGE: _spec("Manage webhooks"),
    P.ORG_DEPARTMENTS_MANAGE: _spec(
        "Create, change, move and archive departments and place people", scopes=("department",)
    ),
    P.ORG_DEPARTMENTS_READ: _spec("Read the department tree", scopes=("department",)),
    P.ORG_IMPORT: _spec("Import departments and people from CSV"),
    P.PII_ACCESS_LOG_READ: _spec("Read the PII access log", locked=True),
    P.PII_REVEAL: _spec("Reveal quarantined personal data", locked=True),
    P.PII_REVEAL_ANY: _spec(
        "Reveal any placeholder on any ticket, credentials included", locked=True
    ),
    P.REPORTS_DASHBOARD_READ: _spec("Read the dashboard"),
    P.REPORTS_INCIDENTS_READ: _spec("Read the incidents report"),
    P.REPORTS_KB_READ: _spec("Read the knowledge report"),
    P.REPORTS_NOTIFICATIONS_READ: _spec("Read the notifications report"),
    P.REPORTS_OPERATIONS_READ: _spec(
        "Read SLA, team, reviewer and satisfaction reports", scopes=("department",)
    ),
    P.REPORTS_REVIEWERS_ALL: _spec("Read every reviewer's figures"),
    P.REPORTS_ROLLOUT_READ: _spec("Read the rollout report"),
    P.REPORTS_SECURITY_READ: _spec("Read the security report"),
    P.REPORTS_SECURITY_DETAIL: _spec("Read the security report's alert detail", locked=True),
    P.REPORTS_TEAMS_READ: _spec("Read a team's figures in reports", scopes=("team",)),
    P.REQUESTER_CHAT: _spec("Ask IT in the chat", staff_only=False),
    P.REQUESTER_DEPARTMENT_READ: _spec(
        "Read your department's tickets, masked", staff_only=False, scopes=("department",)
    ),
    P.REQUESTER_SUBMIT: _spec("Submit a ticket", staff_only=False),
    P.REQUESTER_TICKET_STATUS: _spec("Read a ticket's status and SLA", staff_only=False),
    P.REQUESTER_TICKETS: _spec("Follow, reply to, reopen and rate your tickets", staff_only=False),
    P.REVIEW_FEWSHOT_READ: _spec("Read the active few-shot examples"),
    P.REVIEW_QUEUE_WORK: _spec("Work the review queue"),
    P.ROLLOUT_FLAG_OFF: _spec("Turn a branch back to shadow"),
    P.ROLLOUT_FLAG_ON: _spec("Turn a branch live", locked=True),
    P.ROLLOUT_GATES_MANAGE: _spec("Change a rollout gate", locked=True),
    P.ROLLOUT_READ: _spec("Read rollout state"),
    P.ROLLOUT_THRESHOLDS_READ: _spec("Read the loaded thresholds"),
    P.RUNBOOKS_CATALOG_ACTIVATE: _spec("Turn a runbook on"),
    P.RUNBOOKS_CATALOG_MANAGE: _spec("Create and change runbooks"),
    P.RUNBOOKS_CATALOG_READ: _spec("Read the runbook catalog"),
    P.RUNBOOKS_EXECUTE: _spec("Approve and run a runbook on a reviewed ticket"),
    P.SECURITY_QUEUE_WORK: _spec("Work security alerts and the security queues", locked=True),
    P.SECURITY_SUMMARY_READ: _spec("Read the security summary"),
    P.SELF_NOTIFICATIONS: _spec(
        "Read your notifications and set your preferences", staff_only=False
    ),
    P.SELF_PROFILE: _spec("Read your own profile and access", staff_only=False),
    P.SELF_SESSIONS: _spec("See and end your own sign-ins", staff_only=False),
    P.SLA_MANAGE: _spec("Draft SLA policies and edit calendars and holidays"),
    P.SLA_POLICIES_ACTIVATE: _spec("Activate or retire an SLA policy"),
    P.SLA_READ: _spec("Read SLA policies, calendars and breaches"),
    P.TEAMS_AVAILABILITY_MANAGE: _spec("Set a member's availability"),
    P.TEAMS_AVAILABILITY_OWN: _spec("Set your own availability and leave"),
    P.TEAMS_LEAD: _spec("Lead a team", scopes=("team",)),
    P.TEAMS_MANAGE: _spec("Create and change teams and their members"),
    P.TEAMS_READ: _spec("Read teams, queues and workload"),
    P.TEAMS_SUPERVISE: _spec(
        "Supervise a team: its queue, workload, availability, takes and reassignments",
        scopes=("team",),
    ),
    P.TICKETS_ALL_CATEGORIES: _spec("Work tickets of every category, not only security ones"),
    P.TICKETS_COMMENT: _spec("Comment on a ticket", scopes=("team", "department")),
    P.TICKETS_FIELDS_WRITE: _spec(
        "Write a ticket's workflow fields", scopes=("team", "department")
    ),
    P.TICKETS_LIFECYCLE_READ: _spec(
        "Read a ticket's moves and transfers", scopes=("team", "department")
    ),
    P.TICKETS_MOVE: _spec("Move a ticket between statuses", scopes=("team", "department")),
    P.TICKETS_MOVE_FORCE: _spec("Force a move outside the workflow's transitions", locked=True),
    P.TICKETS_PRIORITY: _spec("Change a ticket's priority", scopes=("team", "department")),
    P.TICKETS_READ: _spec("Read tickets, the board and comments", scopes=("team", "department")),
    P.TICKETS_REASSIGN: _spec("Reassign a ticket", scopes=("team", "department")),
    P.TICKETS_SLA_REBUILD: _spec("Rebuild a ticket's SLA clocks"),
    P.TICKETS_TAKE: _spec("Take a ticket", scopes=("team", "department")),
    P.TICKETS_TRANSFERS_RETRY: _spec("Retry a failed transfer"),
    P.TICKETS_WORKFLOW_CHANGE: _spec("Move a ticket to another workflow"),
    P.WORKFLOWS_MANAGE: _spec("Change workflows"),
    P.WORKFLOWS_READ: _spec("Read workflows"),
}


def area_of(permission: Permission) -> str:
    """The permission's area, its first segment after `perm`."""
    return permission.value.removeprefix(PERMISSION_PREFIX).split(":")[0]


class SystemRole(StrEnum):
    """The roles defined in code (BR-F14-09); copied but never edited or retired."""

    EMPLOYEE = "urn:smart-ticket:role:system:employee"
    TECHNICIAN = "urn:smart-ticket:role:system:technician"
    MANAGER = "urn:smart-ticket:role:system:manager"
    SECURITY = "urn:smart-ticket:role:system:security"
    WORKFLOW_ADMIN = "urn:smart-ticket:role:system:workflow-admin"
    KB_EDITOR = "urn:smart-ticket:role:system:kb-editor"
    INCIDENT_MANAGER = "urn:smart-ticket:role:system:incident-manager"
    TEAM_LEAD = "urn:smart-ticket:role:system:team-lead"
    DEPARTMENT_HEAD = "urn:smart-ticket:role:system:department-head"


BASE_ROLES: dict[UserRole, SystemRole] = {
    UserRole.EMPLOYEE: SystemRole.EMPLOYEE,
    UserRole.TECHNICIAN: SystemRole.TECHNICIAN,
    UserRole.MANAGER: SystemRole.MANAGER,
    UserRole.SECURITY: SystemRole.SECURITY,
}
ADD_ON_ROLES: dict[Capability, SystemRole] = {
    Capability.WORKFLOW_ADMIN: SystemRole.WORKFLOW_ADMIN,
    Capability.KB_EDITOR: SystemRole.KB_EDITOR,
    Capability.INCIDENT_MANAGER: SystemRole.INCIDENT_MANAGER,
}
STRUCTURAL_ROLES = frozenset({SystemRole.TEAM_LEAD, SystemRole.DEPARTMENT_HEAD})

SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[Permission]] = {
    SystemRole.EMPLOYEE: frozenset(
        {
            P.KB_PAGES_READ,
            P.REQUESTER_CHAT,
            P.REQUESTER_SUBMIT,
            P.REQUESTER_TICKET_STATUS,
            P.REQUESTER_TICKETS,
            P.SELF_NOTIFICATIONS,
            P.SELF_PROFILE,
            P.SELF_SESSIONS,
        }
    ),
    SystemRole.TECHNICIAN: frozenset(
        {
            P.TICKETS_ALL_CATEGORIES,
            P.ACCESS_REVIEW_RESPOND,
            P.INCIDENTS_READ,
            P.INCIDENTS_UNLINK,
            P.KB_PAGES_READ,
            P.ORG_DEPARTMENTS_READ,
            P.PII_REVEAL,
            P.REPORTS_DASHBOARD_READ,
            P.REPORTS_OPERATIONS_READ,
            P.REQUESTER_CHAT,
            P.REQUESTER_SUBMIT,
            P.REQUESTER_TICKET_STATUS,
            P.REQUESTER_TICKETS,
            P.REVIEW_FEWSHOT_READ,
            P.REVIEW_QUEUE_WORK,
            P.ROLLOUT_READ,
            P.ROLLOUT_THRESHOLDS_READ,
            P.RUNBOOKS_CATALOG_READ,
            P.RUNBOOKS_EXECUTE,
            P.SELF_NOTIFICATIONS,
            P.SELF_PROFILE,
            P.SELF_SESSIONS,
            P.SLA_READ,
            P.TEAMS_AVAILABILITY_MANAGE,
            P.TEAMS_AVAILABILITY_OWN,
            P.TEAMS_READ,
            P.TICKETS_COMMENT,
            P.TICKETS_FIELDS_WRITE,
            P.TICKETS_LIFECYCLE_READ,
            P.TICKETS_MOVE,
            P.TICKETS_PRIORITY,
            P.TICKETS_READ,
            P.TICKETS_REASSIGN,
            P.TICKETS_TAKE,
            P.TICKETS_TRANSFERS_RETRY,
            P.WORKFLOWS_READ,
        }
    ),
    SystemRole.MANAGER: frozenset(
        {
            P.KB_DRAFTS_WITHDRAW_ANY,
            P.REPORTS_REVIEWERS_ALL,
            P.TEAMS_SUPERVISE,
            P.TICKETS_ALL_CATEGORIES,
            P.ACCESS_GRANT,
            P.ACCESS_PEOPLE_MANAGE,
            P.ACCESS_PEOPLE_READ,
            P.ACCESS_READ,
            P.ACCESS_REVIEW_MANAGE,
            P.ACCESS_REVIEW_RESPOND,
            P.ACCESS_ROLES_MANAGE,
            P.INCIDENTS_READ,
            P.INCIDENTS_UNLINK,
            P.KB_AUTHORITY_LOG_READ,
            P.KB_AUTHORITY_GRANT,
            P.KB_AUTHORITY_QUEUE,
            P.KB_AUTHORITY_RISK_TIER,
            P.KB_DRAFTS_MANAGE,
            P.KB_GAPS_MANAGE,
            P.KB_GRAPH_READ,
            P.KB_GRAPH_REBUILD,
            P.KB_PAGES_CREATE,
            P.KB_PAGES_READ,
            P.KB_PAGES_REINGEST,
            P.NOTIFICATIONS_DELIVERIES_MANAGE,
            P.NOTIFICATIONS_MATRIX_READ,
            P.ORG_DEPARTMENTS_MANAGE,
            P.ORG_DEPARTMENTS_READ,
            P.ORG_IMPORT,
            P.REPORTS_DASHBOARD_READ,
            P.REPORTS_INCIDENTS_READ,
            P.REPORTS_KB_READ,
            P.REPORTS_NOTIFICATIONS_READ,
            P.REPORTS_OPERATIONS_READ,
            P.REPORTS_ROLLOUT_READ,
            P.REPORTS_SECURITY_READ,
            P.REPORTS_TEAMS_READ,
            P.REQUESTER_CHAT,
            P.REQUESTER_SUBMIT,
            P.REQUESTER_TICKET_STATUS,
            P.REQUESTER_TICKETS,
            P.REVIEW_FEWSHOT_READ,
            P.REVIEW_QUEUE_WORK,
            P.ROLLOUT_FLAG_OFF,
            P.ROLLOUT_FLAG_ON,
            P.ROLLOUT_GATES_MANAGE,
            P.ROLLOUT_READ,
            P.ROLLOUT_THRESHOLDS_READ,
            P.RUNBOOKS_CATALOG_ACTIVATE,
            P.RUNBOOKS_CATALOG_READ,
            P.RUNBOOKS_EXECUTE,
            P.SECURITY_SUMMARY_READ,
            P.SELF_NOTIFICATIONS,
            P.SELF_PROFILE,
            P.SELF_SESSIONS,
            P.SLA_POLICIES_ACTIVATE,
            P.SLA_READ,
            P.TEAMS_AVAILABILITY_MANAGE,
            P.TEAMS_AVAILABILITY_OWN,
            P.TEAMS_MANAGE,
            P.TEAMS_READ,
            P.TICKETS_COMMENT,
            P.TICKETS_FIELDS_WRITE,
            P.TICKETS_LIFECYCLE_READ,
            P.TICKETS_MOVE,
            P.TICKETS_MOVE_FORCE,
            P.TICKETS_PRIORITY,
            P.TICKETS_READ,
            P.TICKETS_REASSIGN,
            P.TICKETS_SLA_REBUILD,
            P.TICKETS_TAKE,
            P.TICKETS_TRANSFERS_RETRY,
            P.TICKETS_WORKFLOW_CHANGE,
            P.WORKFLOWS_MANAGE,
            P.WORKFLOWS_READ,
        }
    ),
    SystemRole.SECURITY: frozenset(
        {
            P.PII_REVEAL_ANY,
            P.REPORTS_SECURITY_DETAIL,
            P.ACCESS_READ,
            P.ACCESS_REVIEW_RESPOND,
            P.INCIDENTS_READ,
            P.INCIDENTS_UNLINK,
            P.KB_AUTHORITY_LOG_READ,
            P.KB_PAGES_READ,
            P.ORG_DEPARTMENTS_READ,
            P.PII_ACCESS_LOG_READ,
            P.PII_REVEAL,
            P.REPORTS_ROLLOUT_READ,
            P.REPORTS_SECURITY_READ,
            P.REQUESTER_CHAT,
            P.REQUESTER_SUBMIT,
            P.REQUESTER_TICKET_STATUS,
            P.REQUESTER_TICKETS,
            P.REVIEW_QUEUE_WORK,
            P.ROLLOUT_FLAG_OFF,
            P.ROLLOUT_READ,
            P.ROLLOUT_THRESHOLDS_READ,
            P.SECURITY_QUEUE_WORK,
            P.SECURITY_SUMMARY_READ,
            P.SELF_NOTIFICATIONS,
            P.SELF_PROFILE,
            P.SELF_SESSIONS,
            P.SLA_READ,
            P.TEAMS_AVAILABILITY_MANAGE,
            P.TEAMS_AVAILABILITY_OWN,
            P.TEAMS_READ,
            P.TICKETS_COMMENT,
            P.TICKETS_PRIORITY,
            P.TICKETS_READ,
            P.TICKETS_REASSIGN,
            P.TICKETS_TAKE,
        }
    ),
    SystemRole.WORKFLOW_ADMIN: frozenset(
        {
            P.ACCESS_PEOPLE_READ,
            P.NOTIFICATIONS_DELIVERIES_MANAGE,
            P.NOTIFICATIONS_MATRIX_MANAGE,
            P.NOTIFICATIONS_MATRIX_READ,
            P.NOTIFICATIONS_TEMPLATES_MANAGE,
            P.NOTIFICATIONS_WEBHOOKS_MANAGE,
            P.ORG_DEPARTMENTS_MANAGE,
            P.ORG_DEPARTMENTS_READ,
            P.REPORTS_NOTIFICATIONS_READ,
            P.RUNBOOKS_CATALOG_ACTIVATE,
            P.RUNBOOKS_CATALOG_MANAGE,
            P.RUNBOOKS_CATALOG_READ,
            P.SLA_MANAGE,
            P.SLA_POLICIES_ACTIVATE,
            P.TEAMS_MANAGE,
        }
    ),
    SystemRole.KB_EDITOR: frozenset(
        {
            P.KB_AUTHORITY_LOG_READ,
            P.KB_DRAFTS_MANAGE,
            P.KB_GAPS_MANAGE,
            P.KB_GRAPH_EDIT,
            P.KB_GRAPH_READ,
            P.KB_GRAPH_REBUILD,
            P.KB_PAGES_CREATE,
            P.REPORTS_KB_READ,
        }
    ),
    SystemRole.INCIDENT_MANAGER: frozenset(
        {
            P.INCIDENTS_MANAGE,
            P.INCIDENTS_UNLINK,
            P.REPORTS_INCIDENTS_READ,
        }
    ),
    SystemRole.TEAM_LEAD: frozenset(
        {
            P.REPORTS_TEAMS_READ,
            P.TEAMS_LEAD,
        }
    ),
    SystemRole.DEPARTMENT_HEAD: frozenset(
        {
            P.ACCESS_GRANT_DELEGABLE,
            P.ORG_DEPARTMENTS_MANAGE,
            P.ORG_DEPARTMENTS_READ,
            P.REPORTS_OPERATIONS_READ,
            P.REQUESTER_DEPARTMENT_READ,
        }
    ),
}

SYSTEM_ROLE_NAMES: dict[SystemRole, str] = {
    SystemRole.EMPLOYEE: "Employee",
    SystemRole.TECHNICIAN: "Technician",
    SystemRole.MANAGER: "Manager",
    SystemRole.SECURITY: "Security",
    SystemRole.WORKFLOW_ADMIN: "Workflow admin",
    SystemRole.KB_EDITOR: "Knowledge editor",
    SystemRole.INCIDENT_MANAGER: "Incident manager",
    SystemRole.TEAM_LEAD: "Team lead",
    SystemRole.DEPARTMENT_HEAD: "Department head",
}


def custom_role_urn(name: str) -> str:
    """The URN of a custom role called `name`, e.g. "Read-only auditor" → `…:custom:read-only-auditor`."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return f"{ROLE_PREFIX}custom:{slug}"


def is_role_urn(value: str) -> bool:
    return bool(ROLE_URN.match(value))


def is_permission_urn(value: str) -> bool:
    return bool(PERMISSION_URN.match(value))


def permissions_scopable_at(permissions: frozenset[Permission], scope: ScopeKind) -> bool:
    """Whether every one of `permissions` may be granted at `scope`."""
    return all(scope in PERMISSIONS[p].scopes for p in permissions)
