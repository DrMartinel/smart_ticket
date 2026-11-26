"""System data for access control: permissions, metadata, and system roles (ADR-0045).

Each `Permission` member is a `StrEnum` carrying its own `label`, `staff_only`, `locked`,
and `scopes` so every URN and its metadata are defined once and statically checked at all
`@require(Permission.*)` and `Access.holds(Permission.*)` call sites. URN parsing and
helper logic live in `apps.accounts.utils.catalog`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from apps.accounts.models import Capability, UserRole


class ScopeKind(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    DEPARTMENT = "department"


GLOBAL_AND_TEAM = (ScopeKind.GLOBAL, ScopeKind.TEAM)
GLOBAL_AND_DEPARTMENT = (ScopeKind.GLOBAL, ScopeKind.DEPARTMENT)
ALL_SCOPES = (ScopeKind.GLOBAL, ScopeKind.TEAM, ScopeKind.DEPARTMENT)


def _p(
    urn: str,
    label: str,
    *,
    staff_only: bool = True,
    locked: bool = False,
    scopes: tuple[ScopeKind, ...] = (ScopeKind.GLOBAL,),
) -> tuple[str, str, bool, bool, tuple[ScopeKind, ...]]:
    return (urn, label, staff_only, locked, scopes)


class Permission(StrEnum):
    """Every action core-api gates, named by URN (BR-F14-20), with its catalogue metadata."""

    label: str
    staff_only: bool
    locked: bool
    scopes: tuple[ScopeKind, ...]

    def __new__(
        cls,
        urn: str,
        label: str = "",
        staff_only: bool = True,
        locked: bool = False,
        scopes: tuple[ScopeKind, ...] = (ScopeKind.GLOBAL,),
    ) -> Self:
        obj = str.__new__(cls, urn)
        obj._value_ = urn
        obj.label = label
        obj.staff_only = staff_only
        obj.locked = locked
        obj.scopes = scopes
        return obj

    ACCESS_GRANT = _p(
        "urn:smart-ticket:perm:access:grant",
        "Set a person's base role and grant roles",
        locked=True,
    )
    ACCESS_GRANT_DELEGABLE = _p(
        "urn:smart-ticket:perm:access:grant:delegable",
        "Grant delegable custom roles to people in the departments you head",
        locked=True,
        scopes=GLOBAL_AND_DEPARTMENT,
    )
    ACCESS_PEOPLE_MANAGE = _p(
        "urn:smart-ticket:perm:access:people:manage",
        "Pre-provision, suspend, reactivate and deactivate people",
        locked=True,
    )
    ACCESS_PEOPLE_READ = _p(
        "urn:smart-ticket:perm:access:people:read",
        "List people and their access",
    )
    ACCESS_READ = _p(
        "urn:smart-ticket:perm:access:read",
        "Read roles, grants and access explanations",
    )
    ACCESS_REVIEW_MANAGE = _p(
        "urn:smart-ticket:perm:access:review:manage",
        "Open and close access reviews",
        locked=True,
    )
    ACCESS_REVIEW_RESPOND = _p(
        "urn:smart-ticket:perm:access:review:respond",
        "Answer the access reviews assigned to you",
    )
    ACCESS_ROLES_MANAGE = _p(
        "urn:smart-ticket:perm:access:roles:manage",
        "Create, change and retire custom roles",
        locked=True,
    )
    AGENT_USE = _p(
        "urn:smart-ticket:perm:agent:use",
        "Use the assistant",
        staff_only=False,
    )
    INCIDENTS_MANAGE = _p(
        "urn:smart-ticket:perm:incidents:manage",
        "Declare, confirm, broadcast, resolve and link incidents",
    )
    INCIDENTS_READ = _p(
        "urn:smart-ticket:perm:incidents:read",
        "Read incidents",
    )
    INCIDENTS_UNLINK = _p(
        "urn:smart-ticket:perm:incidents:unlink",
        "Unlink a ticket from an incident",
    )
    INFRA_OPERATE = _p(
        "urn:smart-ticket:perm:infra:operate",
        "Reboot, start, stop and attach on any cloud project",
    )
    INFRA_OPERATE_OWN = _p(
        "urn:smart-ticket:perm:infra:operate:own",
        "Reboot, start and stop your own company's cloud servers",
        staff_only=False,
    )
    INFRA_READ = _p(
        "urn:smart-ticket:perm:infra:read",
        "Read every cloud project's resources, metrics, logs and alerts",
    )
    INFRA_READ_OWN = _p(
        "urn:smart-ticket:perm:infra:read:own",
        "Read your own company's cloud resources, metrics, logs and alerts",
        staff_only=False,
    )
    KB_AUTHORITY_LOG_READ = _p(
        "urn:smart-ticket:perm:kb:authority-log:read",
        "Read the authority log",
    )
    KB_AUTHORITY_GRANT = _p(
        "urn:smart-ticket:perm:kb:authority:grant",
        "Allow or revoke automatic answers from a page",
        locked=True,
    )
    KB_AUTHORITY_QUEUE = _p(
        "urn:smart-ticket:perm:kb:authority:queue",
        "Read the authority queue",
    )
    KB_AUTHORITY_RISK_TIER = _p(
        "urn:smart-ticket:perm:kb:authority:risk-tier",
        "Change a page's risk tier",
        locked=True,
    )
    KB_DRAFTS_MANAGE = _p(
        "urn:smart-ticket:perm:kb:drafts:manage",
        "Write, review and withdraw page drafts",
    )
    KB_DRAFTS_WITHDRAW_ANY = _p(
        "urn:smart-ticket:perm:kb:drafts:withdraw-any",
        "Withdraw anyone's page draft",
    )
    KB_GAPS_MANAGE = _p(
        "urn:smart-ticket:perm:kb:gaps:manage",
        "Read and dismiss knowledge gaps",
    )
    KB_GRAPH_EDIT = _p(
        "urn:smart-ticket:perm:kb:graph:edit",
        "Correct a page's graph",
    )
    KB_GRAPH_READ = _p(
        "urn:smart-ticket:perm:kb:graph:read",
        "Read a page's graph",
    )
    KB_GRAPH_REBUILD = _p(
        "urn:smart-ticket:perm:kb:graph:rebuild",
        "Ask for a page's graph to be rebuilt",
    )
    KB_PAGES_CREATE = _p(
        "urn:smart-ticket:perm:kb:pages:create",
        "Create a help page",
    )
    KB_PAGES_READ = _p(
        "urn:smart-ticket:perm:kb:pages:read",
        "Read the help pages",
        staff_only=False,
    )
    KB_PAGES_REINGEST = _p(
        "urn:smart-ticket:perm:kb:pages:reingest",
        "Re-ingest a help page",
    )
    NOTIFICATIONS_DELIVERIES_MANAGE = _p(
        "urn:smart-ticket:perm:notifications:deliveries:manage",
        "Read and retry deliveries",
    )
    NOTIFICATIONS_MATRIX_MANAGE = _p(
        "urn:smart-ticket:perm:notifications:matrix:manage",
        "Change the notification matrix",
    )
    NOTIFICATIONS_MATRIX_READ = _p(
        "urn:smart-ticket:perm:notifications:matrix:read",
        "Read the notification matrix",
    )
    NOTIFICATIONS_TEMPLATES_MANAGE = _p(
        "urn:smart-ticket:perm:notifications:templates:manage",
        "Change notification templates",
    )
    NOTIFICATIONS_WEBHOOKS_MANAGE = _p(
        "urn:smart-ticket:perm:notifications:webhooks:manage",
        "Manage webhooks",
    )
    ORG_DEPARTMENTS_MANAGE = _p(
        "urn:smart-ticket:perm:org:departments:manage",
        "Create, change, move and archive departments and place people",
        scopes=GLOBAL_AND_DEPARTMENT,
    )
    ORG_DEPARTMENTS_READ = _p(
        "urn:smart-ticket:perm:org:departments:read",
        "Read the department tree",
        scopes=GLOBAL_AND_DEPARTMENT,
    )
    ORG_IMPORT = _p(
        "urn:smart-ticket:perm:org:import",
        "Import departments and people from CSV",
    )
    PII_ACCESS_LOG_READ = _p(
        "urn:smart-ticket:perm:pii:access-log:read",
        "Read the PII access log",
        locked=True,
    )
    PII_REVEAL = _p(
        "urn:smart-ticket:perm:pii:reveal",
        "Reveal quarantined personal data",
        locked=True,
    )
    PII_REVEAL_ANY = _p(
        "urn:smart-ticket:perm:pii:reveal:any",
        "Reveal any placeholder on any ticket, credentials included",
        locked=True,
    )
    REPORTS_DASHBOARD_READ = _p(
        "urn:smart-ticket:perm:reports:dashboard:read",
        "Read the dashboard",
    )
    REPORTS_INCIDENTS_READ = _p(
        "urn:smart-ticket:perm:reports:incidents:read",
        "Read the incidents report",
    )
    REPORTS_KB_READ = _p(
        "urn:smart-ticket:perm:reports:kb:read",
        "Read the knowledge report",
    )
    REPORTS_NOTIFICATIONS_READ = _p(
        "urn:smart-ticket:perm:reports:notifications:read",
        "Read the notifications report",
    )
    REPORTS_OPERATIONS_READ = _p(
        "urn:smart-ticket:perm:reports:operations:read",
        "Read SLA, team, reviewer and satisfaction reports",
        scopes=GLOBAL_AND_DEPARTMENT,
    )
    REPORTS_REVIEWERS_ALL = _p(
        "urn:smart-ticket:perm:reports:reviewers:all",
        "Read every reviewer's figures",
    )
    REPORTS_ROLLOUT_READ = _p(
        "urn:smart-ticket:perm:reports:rollout:read",
        "Read the rollout report",
    )
    REPORTS_SECURITY_READ = _p(
        "urn:smart-ticket:perm:reports:security:read",
        "Read the security report",
    )
    REPORTS_SECURITY_DETAIL = _p(
        "urn:smart-ticket:perm:reports:security:detail",
        "Read the security report's alert detail",
        locked=True,
    )
    REPORTS_TEAMS_READ = _p(
        "urn:smart-ticket:perm:reports:teams:read",
        "Read a team's figures in reports",
        scopes=GLOBAL_AND_TEAM,
    )
    REQUESTER_CHAT = _p(
        "urn:smart-ticket:perm:requester:chat",
        "Ask IT in the chat",
        staff_only=False,
    )
    REQUESTER_DEPARTMENT_READ = _p(
        "urn:smart-ticket:perm:requester:department:read",
        "Read your department's tickets, masked",
        staff_only=False,
        scopes=GLOBAL_AND_DEPARTMENT,
    )
    REQUESTER_SUBMIT = _p(
        "urn:smart-ticket:perm:requester:submit",
        "Submit a ticket",
        staff_only=False,
    )
    REQUESTER_TICKET_STATUS = _p(
        "urn:smart-ticket:perm:requester:ticket-status",
        "Read a ticket's status and SLA",
        staff_only=False,
    )
    REQUESTER_TICKETS = _p(
        "urn:smart-ticket:perm:requester:tickets",
        "Follow, reply to, reopen and rate your tickets",
        staff_only=False,
    )
    REVIEW_FEWSHOT_READ = _p(
        "urn:smart-ticket:perm:review:fewshot:read",
        "Read the active few-shot examples",
    )
    REVIEW_QUEUE_WORK = _p(
        "urn:smart-ticket:perm:review:queue:work",
        "Work the review queue",
    )
    ROLLOUT_FLAG_OFF = _p(
        "urn:smart-ticket:perm:rollout:flag:off",
        "Turn a branch back to shadow",
    )
    ROLLOUT_FLAG_ON = _p(
        "urn:smart-ticket:perm:rollout:flag:on",
        "Turn a branch live",
        locked=True,
    )
    ROLLOUT_GATES_MANAGE = _p(
        "urn:smart-ticket:perm:rollout:gates:manage",
        "Change a rollout gate",
        locked=True,
    )
    ROLLOUT_READ = _p(
        "urn:smart-ticket:perm:rollout:read",
        "Read rollout state",
    )
    ROLLOUT_THRESHOLDS_READ = _p(
        "urn:smart-ticket:perm:rollout:thresholds:read",
        "Read the loaded thresholds",
    )
    RUNBOOKS_CATALOG_ACTIVATE = _p(
        "urn:smart-ticket:perm:runbooks:catalog:activate",
        "Turn a runbook on",
    )
    RUNBOOKS_CATALOG_MANAGE = _p(
        "urn:smart-ticket:perm:runbooks:catalog:manage",
        "Create and change runbooks",
    )
    RUNBOOKS_CATALOG_READ = _p(
        "urn:smart-ticket:perm:runbooks:catalog:read",
        "Read the runbook catalog",
    )
    RUNBOOKS_EXECUTE = _p(
        "urn:smart-ticket:perm:runbooks:execute",
        "Approve and run a runbook on a reviewed ticket",
    )
    SECURITY_QUEUE_WORK = _p(
        "urn:smart-ticket:perm:security:queue:work",
        "Work security alerts and the security queues",
        locked=True,
    )
    SECURITY_SUMMARY_READ = _p(
        "urn:smart-ticket:perm:security:summary:read",
        "Read the security summary",
    )
    SELF_NOTIFICATIONS = _p(
        "urn:smart-ticket:perm:self:notifications",
        "Read your notifications and set your preferences",
        staff_only=False,
    )
    SELF_PROFILE = _p(
        "urn:smart-ticket:perm:self:profile",
        "Read your own profile and access",
        staff_only=False,
    )
    SELF_SESSIONS = _p(
        "urn:smart-ticket:perm:self:sessions",
        "See and end your own sign-ins",
        staff_only=False,
    )
    SLA_MANAGE = _p(
        "urn:smart-ticket:perm:sla:manage",
        "Draft SLA policies and edit calendars and holidays",
    )
    SLA_POLICIES_ACTIVATE = _p(
        "urn:smart-ticket:perm:sla:policies:activate",
        "Activate or retire an SLA policy",
    )
    SLA_READ = _p(
        "urn:smart-ticket:perm:sla:read",
        "Read SLA policies, calendars and breaches",
    )
    TEAMS_AVAILABILITY_MANAGE = _p(
        "urn:smart-ticket:perm:teams:availability:manage",
        "Set a member's availability",
    )
    TEAMS_AVAILABILITY_OWN = _p(
        "urn:smart-ticket:perm:teams:availability:own",
        "Set your own availability and leave",
    )
    TEAMS_LEAD = _p(
        "urn:smart-ticket:perm:teams:lead",
        "Lead a team",
        scopes=GLOBAL_AND_TEAM,
    )
    TEAMS_MANAGE = _p(
        "urn:smart-ticket:perm:teams:manage",
        "Create and change teams and their members",
    )
    TEAMS_READ = _p(
        "urn:smart-ticket:perm:teams:read",
        "Read teams, queues and workload",
    )
    TEAMS_SUPERVISE = _p(
        "urn:smart-ticket:perm:teams:supervise",
        "Supervise a team: its queue, workload, availability, takes and reassignments",
        scopes=GLOBAL_AND_TEAM,
    )
    TICKETS_ALL_CATEGORIES = _p(
        "urn:smart-ticket:perm:tickets:all-categories",
        "Work tickets of every category, not only security ones",
    )
    TICKETS_COMMENT = _p(
        "urn:smart-ticket:perm:tickets:comment",
        "Comment on a ticket",
        scopes=ALL_SCOPES,
    )
    TICKETS_FIELDS_WRITE = _p(
        "urn:smart-ticket:perm:tickets:fields:write",
        "Write a ticket's workflow fields",
        scopes=ALL_SCOPES,
    )
    TICKETS_LIFECYCLE_READ = _p(
        "urn:smart-ticket:perm:tickets:lifecycle:read",
        "Read a ticket's moves and transfers",
        scopes=ALL_SCOPES,
    )
    TICKETS_MOVE = _p(
        "urn:smart-ticket:perm:tickets:move",
        "Move a ticket between statuses",
        scopes=ALL_SCOPES,
    )
    TICKETS_MOVE_FORCE = _p(
        "urn:smart-ticket:perm:tickets:move:force",
        "Force a move outside the workflow's transitions",
        locked=True,
    )
    TICKETS_PRIORITY = _p(
        "urn:smart-ticket:perm:tickets:priority",
        "Change a ticket's priority",
        scopes=ALL_SCOPES,
    )
    TICKETS_READ = _p(
        "urn:smart-ticket:perm:tickets:read",
        "Read tickets, the board and comments",
        scopes=ALL_SCOPES,
    )
    TICKETS_REASSIGN = _p(
        "urn:smart-ticket:perm:tickets:reassign",
        "Reassign a ticket",
        scopes=ALL_SCOPES,
    )
    TICKETS_SLA_REBUILD = _p(
        "urn:smart-ticket:perm:tickets:sla:rebuild",
        "Rebuild a ticket's SLA clocks",
    )
    TICKETS_TAKE = _p(
        "urn:smart-ticket:perm:tickets:take",
        "Take a ticket",
        scopes=ALL_SCOPES,
    )
    TICKETS_TRANSFERS_RETRY = _p(
        "urn:smart-ticket:perm:tickets:transfers:retry",
        "Retry a failed transfer",
    )
    TICKETS_WORKFLOW_CHANGE = _p(
        "urn:smart-ticket:perm:tickets:workflow:change",
        "Move a ticket to another workflow",
    )
    WORKFLOWS_MANAGE = _p(
        "urn:smart-ticket:perm:workflows:manage",
        "Change workflows",
    )
    WORKFLOWS_READ = _p(
        "urn:smart-ticket:perm:workflows:read",
        "Read workflows",
    )


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
            Permission.AGENT_USE,
            Permission.INFRA_OPERATE_OWN,
            Permission.INFRA_READ_OWN,
            Permission.KB_PAGES_READ,
            Permission.REQUESTER_CHAT,
            Permission.REQUESTER_SUBMIT,
            Permission.REQUESTER_TICKET_STATUS,
            Permission.REQUESTER_TICKETS,
            Permission.SELF_NOTIFICATIONS,
            Permission.SELF_PROFILE,
            Permission.SELF_SESSIONS,
        }
    ),
    SystemRole.TECHNICIAN: frozenset(
        {
            Permission.AGENT_USE,
            Permission.TICKETS_ALL_CATEGORIES,
            Permission.ACCESS_REVIEW_RESPOND,
            Permission.INCIDENTS_READ,
            Permission.INCIDENTS_UNLINK,
            Permission.INFRA_OPERATE,
            Permission.INFRA_READ,
            Permission.KB_PAGES_READ,
            Permission.ORG_DEPARTMENTS_READ,
            Permission.PII_REVEAL,
            Permission.REPORTS_DASHBOARD_READ,
            Permission.REPORTS_OPERATIONS_READ,
            Permission.REQUESTER_CHAT,
            Permission.REQUESTER_SUBMIT,
            Permission.REQUESTER_TICKET_STATUS,
            Permission.REQUESTER_TICKETS,
            Permission.REVIEW_FEWSHOT_READ,
            Permission.REVIEW_QUEUE_WORK,
            Permission.ROLLOUT_READ,
            Permission.ROLLOUT_THRESHOLDS_READ,
            Permission.RUNBOOKS_CATALOG_READ,
            Permission.RUNBOOKS_EXECUTE,
            Permission.SELF_NOTIFICATIONS,
            Permission.SELF_PROFILE,
            Permission.SELF_SESSIONS,
            Permission.SLA_READ,
            Permission.TEAMS_AVAILABILITY_MANAGE,
            Permission.TEAMS_AVAILABILITY_OWN,
            Permission.TEAMS_READ,
            Permission.TICKETS_COMMENT,
            Permission.TICKETS_FIELDS_WRITE,
            Permission.TICKETS_LIFECYCLE_READ,
            Permission.TICKETS_MOVE,
            Permission.TICKETS_PRIORITY,
            Permission.TICKETS_READ,
            Permission.TICKETS_REASSIGN,
            Permission.TICKETS_TAKE,
            Permission.TICKETS_TRANSFERS_RETRY,
            Permission.WORKFLOWS_READ,
        }
    ),
    SystemRole.MANAGER: frozenset(
        {
            Permission.AGENT_USE,
            Permission.KB_DRAFTS_WITHDRAW_ANY,
            Permission.REPORTS_REVIEWERS_ALL,
            Permission.TEAMS_SUPERVISE,
            Permission.TICKETS_ALL_CATEGORIES,
            Permission.ACCESS_GRANT,
            Permission.ACCESS_PEOPLE_MANAGE,
            Permission.ACCESS_PEOPLE_READ,
            Permission.ACCESS_READ,
            Permission.ACCESS_REVIEW_MANAGE,
            Permission.ACCESS_REVIEW_RESPOND,
            Permission.ACCESS_ROLES_MANAGE,
            Permission.INCIDENTS_READ,
            Permission.INCIDENTS_UNLINK,
            Permission.KB_AUTHORITY_LOG_READ,
            Permission.KB_AUTHORITY_GRANT,
            Permission.KB_AUTHORITY_QUEUE,
            Permission.KB_AUTHORITY_RISK_TIER,
            Permission.KB_DRAFTS_MANAGE,
            Permission.KB_GAPS_MANAGE,
            Permission.KB_GRAPH_READ,
            Permission.KB_GRAPH_REBUILD,
            Permission.KB_PAGES_CREATE,
            Permission.KB_PAGES_READ,
            Permission.KB_PAGES_REINGEST,
            Permission.NOTIFICATIONS_DELIVERIES_MANAGE,
            Permission.NOTIFICATIONS_MATRIX_READ,
            Permission.ORG_DEPARTMENTS_MANAGE,
            Permission.ORG_DEPARTMENTS_READ,
            Permission.ORG_IMPORT,
            Permission.REPORTS_DASHBOARD_READ,
            Permission.REPORTS_INCIDENTS_READ,
            Permission.REPORTS_KB_READ,
            Permission.REPORTS_NOTIFICATIONS_READ,
            Permission.REPORTS_OPERATIONS_READ,
            Permission.REPORTS_ROLLOUT_READ,
            Permission.REPORTS_SECURITY_READ,
            Permission.REPORTS_TEAMS_READ,
            Permission.REQUESTER_CHAT,
            Permission.REQUESTER_SUBMIT,
            Permission.REQUESTER_TICKET_STATUS,
            Permission.REQUESTER_TICKETS,
            Permission.REVIEW_FEWSHOT_READ,
            Permission.REVIEW_QUEUE_WORK,
            Permission.ROLLOUT_FLAG_OFF,
            Permission.ROLLOUT_FLAG_ON,
            Permission.ROLLOUT_GATES_MANAGE,
            Permission.ROLLOUT_READ,
            Permission.ROLLOUT_THRESHOLDS_READ,
            Permission.RUNBOOKS_CATALOG_ACTIVATE,
            Permission.RUNBOOKS_CATALOG_READ,
            Permission.RUNBOOKS_EXECUTE,
            Permission.SECURITY_SUMMARY_READ,
            Permission.SELF_NOTIFICATIONS,
            Permission.SELF_PROFILE,
            Permission.SELF_SESSIONS,
            Permission.SLA_POLICIES_ACTIVATE,
            Permission.SLA_READ,
            Permission.TEAMS_AVAILABILITY_MANAGE,
            Permission.TEAMS_AVAILABILITY_OWN,
            Permission.TEAMS_MANAGE,
            Permission.TEAMS_READ,
            Permission.TICKETS_COMMENT,
            Permission.TICKETS_FIELDS_WRITE,
            Permission.TICKETS_LIFECYCLE_READ,
            Permission.TICKETS_MOVE,
            Permission.TICKETS_MOVE_FORCE,
            Permission.TICKETS_PRIORITY,
            Permission.TICKETS_READ,
            Permission.TICKETS_REASSIGN,
            Permission.TICKETS_SLA_REBUILD,
            Permission.TICKETS_TAKE,
            Permission.TICKETS_TRANSFERS_RETRY,
            Permission.TICKETS_WORKFLOW_CHANGE,
            Permission.WORKFLOWS_MANAGE,
            Permission.WORKFLOWS_READ,
        }
    ),
    SystemRole.SECURITY: frozenset(
        {
            Permission.AGENT_USE,
            Permission.PII_REVEAL_ANY,
            Permission.REPORTS_SECURITY_DETAIL,
            Permission.ACCESS_READ,
            Permission.ACCESS_REVIEW_RESPOND,
            Permission.INCIDENTS_READ,
            Permission.INCIDENTS_UNLINK,
            Permission.KB_AUTHORITY_LOG_READ,
            Permission.KB_PAGES_READ,
            Permission.ORG_DEPARTMENTS_READ,
            Permission.PII_ACCESS_LOG_READ,
            Permission.PII_REVEAL,
            Permission.REPORTS_ROLLOUT_READ,
            Permission.REPORTS_SECURITY_READ,
            Permission.REQUESTER_CHAT,
            Permission.REQUESTER_SUBMIT,
            Permission.REQUESTER_TICKET_STATUS,
            Permission.REQUESTER_TICKETS,
            Permission.REVIEW_QUEUE_WORK,
            Permission.ROLLOUT_FLAG_OFF,
            Permission.ROLLOUT_READ,
            Permission.ROLLOUT_THRESHOLDS_READ,
            Permission.SECURITY_QUEUE_WORK,
            Permission.SECURITY_SUMMARY_READ,
            Permission.SELF_NOTIFICATIONS,
            Permission.SELF_PROFILE,
            Permission.SELF_SESSIONS,
            Permission.SLA_READ,
            Permission.TEAMS_AVAILABILITY_MANAGE,
            Permission.TEAMS_AVAILABILITY_OWN,
            Permission.TEAMS_READ,
            Permission.TICKETS_COMMENT,
            Permission.TICKETS_PRIORITY,
            Permission.TICKETS_READ,
            Permission.TICKETS_REASSIGN,
            Permission.TICKETS_TAKE,
        }
    ),
    SystemRole.WORKFLOW_ADMIN: frozenset(
        {
            Permission.ACCESS_PEOPLE_READ,
            Permission.NOTIFICATIONS_DELIVERIES_MANAGE,
            Permission.NOTIFICATIONS_MATRIX_MANAGE,
            Permission.NOTIFICATIONS_MATRIX_READ,
            Permission.NOTIFICATIONS_TEMPLATES_MANAGE,
            Permission.NOTIFICATIONS_WEBHOOKS_MANAGE,
            Permission.ORG_DEPARTMENTS_MANAGE,
            Permission.ORG_DEPARTMENTS_READ,
            Permission.REPORTS_NOTIFICATIONS_READ,
            Permission.RUNBOOKS_CATALOG_ACTIVATE,
            Permission.RUNBOOKS_CATALOG_MANAGE,
            Permission.RUNBOOKS_CATALOG_READ,
            Permission.SLA_MANAGE,
            Permission.SLA_POLICIES_ACTIVATE,
            Permission.TEAMS_MANAGE,
        }
    ),
    SystemRole.KB_EDITOR: frozenset(
        {
            Permission.KB_AUTHORITY_LOG_READ,
            Permission.KB_DRAFTS_MANAGE,
            Permission.KB_GAPS_MANAGE,
            Permission.KB_GRAPH_EDIT,
            Permission.KB_GRAPH_READ,
            Permission.KB_GRAPH_REBUILD,
            Permission.KB_PAGES_CREATE,
            Permission.REPORTS_KB_READ,
        }
    ),
    SystemRole.INCIDENT_MANAGER: frozenset(
        {
            Permission.INCIDENTS_MANAGE,
            Permission.INCIDENTS_UNLINK,
            Permission.REPORTS_INCIDENTS_READ,
        }
    ),
    SystemRole.TEAM_LEAD: frozenset(
        {
            Permission.REPORTS_TEAMS_READ,
            Permission.TEAMS_LEAD,
        }
    ),
    SystemRole.DEPARTMENT_HEAD: frozenset(
        {
            Permission.ACCESS_GRANT_DELEGABLE,
            Permission.ORG_DEPARTMENTS_MANAGE,
            Permission.ORG_DEPARTMENTS_READ,
            Permission.REPORTS_OPERATIONS_READ,
            Permission.REQUESTER_DEPARTMENT_READ,
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
