"""Users, consent records and the audit log.

Two constraints the previous pass already got right and that are preserved here
deliberately, because they are easy to break by accident:

- `linked_player_id` is unique across users. One player, at most one login.
- a minor's consent is granted by a guardian and attributed to them by name.
  `Consent.guardian_name` is nullable in the model with enforcement left to the
  app layer, so the generator is currently the only thing that keeps the
  invariant true in the data.
"""

from __future__ import annotations

from datetime import date, timedelta

from .config import GeneratorConfig
from .orm import AuditLog, Consent, Organization, User, enums
from .players import PlayerProfile
from .reference import AUDIT_ACTIONS
from .rng import Rng

# A placeholder that is obviously not a real hash, so nobody can mistake this for
# a credential. The security track's decision record settles the real algorithm.
PLACEHOLDER_HASH = "$synthetic$not-a-real-hash$do-not-use"


def generate_users(
    rng: Rng,
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    orgs: list[Organization],
) -> list[User]:
    cfg = config.accounts
    users: list[User] = []
    org_pool = [o for o in orgs if o.type != enums.OrganizationType.FEDERATION.value]
    federations = [o for o in orgs if o.type == enums.OrganizationType.FEDERATION.value]

    def make(role: str, organization_id, linked_player_id=None) -> User:
        name = rng.faker.eg_full_name(rng.choice(["male", "female"]))
        # Deterministic, collision-free, and obviously synthetic.
        local = f"{role}.{len(users) + 1:03d}"
        return User(
            id=rng.uuid(),
            email=f"{local}@northstar.test",
            password_hash=PLACEHOLDER_HASH,
            full_name=name,
            role=role,
            organization_id=organization_id,
            linked_player_id=linked_player_id,
            is_active=rng.chance(0.94),
            last_login_at=None,
        )

    for _ in range(cfg.n_coaches):
        users.append(make(enums.UserRole.COACH.value, rng.choice(org_pool).id if org_pool else None))
    for _ in range(cfg.n_scouts):
        users.append(make(enums.UserRole.SCOUT.value, rng.choice(org_pool).id if org_pool else None))
    for _ in range(cfg.n_federation_staff):
        users.append(
            make(
                enums.UserRole.FEDERATION.value,
                rng.choice(federations).id if federations else None,
            )
        )
    for _ in range(cfg.n_admins):
        users.append(make(enums.UserRole.ADMIN.value, None))

    # Player accounts. Adults only, and at most one per player: linked_player_id
    # is drawn without replacement, which is what keeps it unique.
    adults = [p for p in profiles if not p.player.is_minor]
    n_player_accounts = round(len(adults) * cfg.player_account_fraction)
    for profile in rng.sample(adults, n_player_accounts):
        users.append(
            make(
                enums.UserRole.PLAYER.value,
                None,
                linked_player_id=profile.id,
            )
        )

    return users


def generate_consents(
    rng: Rng, config: GeneratorConfig, profiles: list[PlayerProfile]
) -> list[Consent]:
    rows: list[Consent] = []
    reference = config.population.reference_date

    """Consent is signed once, at sign-up, for every purpose.

    The operating model: an academy joins the platform, and joining means each player's
    guardian (or the player, once an adult) signs one form covering storage, analytics and
    scouting visibility. So every synthetic player holds all three, granted and open-ended.
    The consent check in `apps/api/app/services/access.py` still runs on every scout
    request; it simply never finds a missing consent in this dataset. A withdrawal is a
    row with `granted=False` and hides the minor again, which is the safeguard the pitch
    promises parents.
    """
    rows: list[Consent] = []
    reference = config.population.reference_date

    for profile in profiles:
        player = profile.player
        # One signature per player: one guardian, one date, one form.
        if player.is_minor:
            guardian = rng.faker.eg_full_name("male" if rng.chance(0.72) else "female")
            granted_by = f"guardian:{guardian}"
        else:
            guardian = None
            granted_by = "player"
        signed_on = reference - timedelta(days=rng.randint(30, 900))

        for purpose in (
            enums.ConsentPurpose.DATA_STORAGE.value,
            enums.ConsentPurpose.ANALYTICS.value,
            enums.ConsentPurpose.SCOUTING_VISIBILITY.value,
        ):
            rows.append(
                Consent(
                    id=rng.uuid(),
                    player_id=profile.id,
                    purpose=purpose,
                    granted=True,
                    granted_by=granted_by,
                    guardian_name=guardian,
                    valid_from=signed_on,
                    valid_until=None,
                    document_ref=f"consent/{profile.id}/signup.pdf",
                )
            )

    return rows


def generate_audit_log(
    rng: Rng,
    config: GeneratorConfig,
    users: list[User],
    profiles: list[PlayerProfile],
) -> list[AuditLog]:
    """Audit events.

    Note `event_metadata=`, not `metadata=`. The column is called metadata in
    Postgres; the Python attribute is renamed because `metadata` is reserved on
    the declarative Base. Constructing the model here rather than writing a dict
    to JSON is what makes that impossible to get wrong.
    """
    cfg = config.accounts
    reference = config.population.reference_date
    rows: list[AuditLog] = []

    if not users:
        return rows

    for _ in range(cfg.n_audit_events):
        action, entity_type = rng.choice(AUDIT_ACTIONS)
        actor = rng.choice(users) if rng.chance(0.92) else None  # None = system action
        entity_id = None
        if entity_type == "Player" and profiles:
            entity_id = rng.choice(profiles).id

        when = _as_datetime(reference - timedelta(days=rng.randint(0, 400))) + timedelta(
            seconds=rng.randint(0, 86399)
        )

        payload: dict = {"request_id": f"req-{rng.randint(10**7, 10**8 - 1)}"}
        if action == "player.update":
            payload["changed_fields"] = rng.sample(
                ["position", "known_as", "tier", "nationality"], rng.randint(1, 2)
            )
        elif action == "login.failure":
            payload["reason"] = rng.choice(["bad_password", "unknown_email", "locked"])
        elif action == "search.run":
            payload["filters"] = {"tier": rng.choice(["youth", "pro", "diaspora"])}

        rows.append(
            AuditLog(
                id=rng.uuid(),
                actor_user_id=actor.id if actor else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                event_metadata=payload,
                ip_address=f"197.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                created_at=when,
            )
        )

    return rows


def _as_datetime(day: date):
    from datetime import datetime, timezone

    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
