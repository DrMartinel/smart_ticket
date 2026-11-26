"""Seeds the six categories the enum and `category.v2.json` define, each description copied from
that question's criteria, and marks `security` as the security category (ADR-0049)."""

from django.db import migrations

SECURITY = "security"

# slug, name, sort order, description (category.v2.json `criteria[slug].what`, verbatim).
CATEGORIES = [
    (
        "hardware",
        "Hardware",
        1,
        "Compute and virtual desktops: a specific EC2 instance or Amazon WorkSpace — it will not start or stop, fails status checks, runs out of disk or memory, is slow, or cannot be connected to over SSH/RDP or the WorkSpaces client when the instance itself is the problem. Instance types, EBS volumes, AMIs, dedicated hosts, the agents and patches on an instance, and WorkSpace bundles belong here too.",
    ),
    (
        "software",
        "Software",
        2,
        "Applications and managed services: Lambda functions (errors, timeouts, throttling, permissions a function needs at runtime), Amazon SES email (sending, bounces, sandbox limits, deliverability, DKIM/SPF), other managed services that are not security services (CloudWatch, Grafana, IoT rules, Kinesis), deployments and application errors.",
    ),
    (
        "network",
        "Network",
        3,
        "Connectivity: VPCs, subnets, route tables, internet and NAT gateways, security groups and network ACLs, VPC peering, DNS resolution, Site-to-Site VPN, and AWS Client VPN (cannot connect, connected but cannot reach resources, slow tunnel).",
    ),
    (
        "access",
        "Access",
        4,
        "Identity and permissions as the need itself: IAM users, groups, roles and policies; IAM Identity Center (SSO, the AWS access portal, permission sets); console sign-in, passwords, MFA devices, access keys; requests to grant, change or remove a person's or team's access to ANY account, service or resource, including access to a security service; an AccessDenied / \"not authorized to perform\" error the user asks to fix by changing their own permissions. Access to sensitive resources (production accounts, billing, KMS keys) needs extra approval but is still `access`, not `security`. An access error met while setting up another service (an export to an S3 bucket, an event destination, a trigger between services) is that service's category.",
    ),
    (
        "security",
        "Security",
        5,
        "Threats, incidents and the security services: GuardDuty findings, failed Security Hub controls, compromised or leaked credentials (e.g. access keys pushed to a public repository), unauthorized activity in an account, abuse or phishing reports; and setting up, configuring, operating or troubleshooting a security service itself (GuardDuty and its agents, Security Hub and its automation rules and integrations, S3 malware protection, Amazon Inspector, Macie, AWS WAF and Shield), even when nothing is wrong yet. A request for a person's permission to use a security service is `access`; a routine permission request is never `security`.",
    ),
    (
        "other",
        "Other",
        6,
        "Not a cloud-platform or IT matter, even though it arrived as a ticket: HR (leave, payroll, benefits), facilities, office administration. Office hardware such as printers is also `other` here: this desk supports the AWS platform, not office equipment.",
    ),
]


def seed(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    for slug, name, sort_order, description in CATEGORIES:
        Category.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_security": slug == SECURITY,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("categories", "Category").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
