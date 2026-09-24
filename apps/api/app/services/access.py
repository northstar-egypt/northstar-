"""Who may see what.

This module is the whole of the read API's access control. It is deliberately one file: the
security workstream has to be able to read every rule in one sitting, and every rule here is
meant to become a test in the RBAC suite.

The rules come from `docs/schema.md` ("Role is the anchor of the access-control workstream")
and `docs/threat-model.md` (threat 1, broken access control), not from invention:

  coach        log and edit players within their academy or club
  scout        search and view across scope, cannot edit player records
  federation   oversight and review dashboards, broad read, review actions
  player       view and manage their own profile and self-submissions
  admin        system administration

Two principles the rest of the API depends on:

**Consent gates minors, not adults.** `docs/schema.md`: "The application must check relevant
consent before exposing a minor's profile to scouts." A minor without a granted, in-date
`scouting_visibility` consent is not visible to a scout. Their own coach still sees them,
because the coach is the one who logged them and consent for scouting visibility is not
consent to exist.

**Withheld is not the same as absent.** A scout who matches a minor without consent gets a
result marked `withheld` with the identifying fields stripped, rather than a silently shorter
list. Whether that is right is still open (see docs/wireframes/README.md, "Consent gating
behaviour"), and the wireframe drew the locked card, so that is what this implements. The
shape makes the other choice a one-line change in the search service.

What is deliberately NOT here: authentication. There is no session, no token and no password
check, because the auth approach is an open decision on the board. `app.deps` resolves a
caller from a development header and this module decides what that caller may see. When real
auth lands it replaces the resolution step and leaves these rules untouched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models.consent import Consent
from app.models.enums import ConsentPurpose, PlayerStatus, UserRole
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.models.user import User


@dataclass(frozen=True)
class Caller:
    """The resolved identity a request acts as."""

    user_id: uuid.UUID
    role: str
    organization_id: uuid.UUID | None
    linked_player_id: uuid.UUID | None
    full_name: str = ""
    email: str = ""
    organization_name: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_federation(self) -> bool:
        return self.role == UserRole.FEDERATION

    @property
    def is_scout(self) -> bool:
        return self.role == UserRole.SCOUT

    @property
    def is_coach(self) -> bool:
        return self.role == UserRole.COACH

    @property
    def is_player(self) -> bool:
        return self.role == UserRole.PLAYER


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def consent_subquery(purpose: str, on_date: date | None = None):
    """Player ids holding a granted, in-date consent for one purpose."""
    on_date = on_date or date.today()
    return (
        select(Consent.player_id)
        .where(Consent.purpose == purpose)
        .where(Consent.granted.is_(True))
        .where(Consent.valid_from <= on_date)
        .where(or_(Consent.valid_until.is_(None), Consent.valid_until >= on_date))
    )


def consent_state(db: Session, player_id: uuid.UUID) -> dict[str, bool]:
    """Current granted state per purpose for one player.

    A purpose with no row at all is False rather than missing. Absence of consent is not
    consent, and a UI that renders a missing key as blank would show nothing where it should
    show a warning.
    """
    today = date.today()
    rows = db.execute(
        select(Consent.purpose, Consent.granted)
        .where(Consent.player_id == player_id)
        .where(Consent.valid_from <= today)
        .where(or_(Consent.valid_until.is_(None), Consent.valid_until >= today))
    ).all()
    state = {purpose.value: False for purpose in ConsentPurpose}
    for purpose, granted in rows:
        state[purpose] = state.get(purpose, False) or bool(granted)
    return state


def consent_complete(state: dict[str, bool]) -> bool:
    """True when every purpose the platform needs is granted.

    Storage and analytics are what the platform itself runs on. Scouting visibility is
    excluded on purpose: declining to be visible to scouts is a legitimate choice and must not
    show up on a coach's dashboard as an incomplete record to chase.
    """
    return bool(
        state.get(ConsentPurpose.DATA_STORAGE.value)
        and state.get(ConsentPurpose.ANALYTICS.value)
    )


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


def visible_players(caller: Caller, *, stmt: Select | None = None) -> Select:
    """Narrow a Player query to the rows this caller may see at all.

    Coaches and players get a hard filter: rows outside their scope do not exist as far as
    the query is concerned. Scouts and federation staff get the full active population here,
    and consent gating for minors is applied per row afterwards, because a scout is told that
    a withheld player exists rather than having them vanish.
    """
    stmt = select(Player) if stmt is None else stmt
    stmt = stmt.where(Player.status != PlayerStatus.MERGED)

    if caller.is_admin or caller.is_federation or caller.is_scout:
        return stmt

    if caller.is_coach:
        if caller.organization_id is None:
            # A coach with no organization can see nobody. Failing closed beats failing
            # open, and it surfaces the broken account instead of leaking a squad.
            return stmt.where(Player.id.is_(None))
        return stmt.where(
            Player.id.in_(
                select(PlayerOrganization.player_id)
                .where(PlayerOrganization.organization_id == caller.organization_id)
                .where(PlayerOrganization.end_date.is_(None))
            )
        )

    if caller.is_player:
        if caller.linked_player_id is None:
            return stmt.where(Player.id.is_(None))
        return stmt.where(Player.id == caller.linked_player_id)

    # Unknown role. Fail closed rather than guessing.
    return stmt.where(Player.id.is_(None))


def may_view(db: Session, caller: Caller, player: Player) -> tuple[bool, str | None]:
    """Whether this caller may see this player's identifying data, and why not.

    Returns (allowed, reason_when_withheld). A scout looking at a minor without scouting
    consent gets (False, reason), which the search service renders as a locked card.
    """
    if caller.is_admin or caller.is_federation:
        return True, None

    if caller.is_player:
        allowed = caller.linked_player_id == player.id
        return allowed, None if allowed else "Not your record."

    if caller.is_coach:
        if caller.organization_id is None:
            return False, "Your account is not attached to an organization."
        in_squad = db.execute(
            select(PlayerOrganization.id)
            .where(PlayerOrganization.player_id == player.id)
            .where(PlayerOrganization.organization_id == caller.organization_id)
            .where(PlayerOrganization.end_date.is_(None))
            .limit(1)
        ).first()
        if in_squad:
            return True, None
        return False, "This player is not in your organization."

    if caller.is_scout:
        if not player.is_minor:
            return True, None
        state = consent_state(db, player.id)
        if state.get(ConsentPurpose.SCOUTING_VISIBILITY.value):
            return True, None
        return False, (
            "This player is a minor and has no current consent for scouting visibility."
        )

    return False, "Your role does not permit viewing player records."


def permissions(db: Session, caller: Caller, player: Player) -> dict[str, bool]:
    """The permissions object the player profile renders from.

    The frontend is explicitly not allowed to derive this from the role. See the comment at
    the top of `apps/web/app/(app)/players/[id]/page.tsx`.
    """
    viewable, _ = may_view(db, caller, player)
    if not viewable:
        return {"can_edit": False, "can_log": False, "can_see_flags": False}

    if caller.is_admin:
        return {"can_edit": True, "can_log": True, "can_see_flags": True}

    if caller.is_coach:
        # Coaches only reach here for players in their own organization.
        return {"can_edit": True, "can_log": True, "can_see_flags": True}

    if caller.is_federation:
        # Broad read and review actions, but federations do not edit club records.
        return {"can_edit": False, "can_log": False, "can_see_flags": True}

    if caller.is_scout:
        return {"can_edit": False, "can_log": False, "can_see_flags": True}

    if caller.is_player:
        # A player may manage their own record but does not see the models' flags about
        # themselves. There is no route for them to dispute one yet, so showing it would be
        # telling a child a machine has doubts about them with nothing they can do. Noted as
        # an open fairness question in the player profile wireframe.
        return {"can_edit": True, "can_log": False, "can_see_flags": False}

    return {"can_edit": False, "can_log": False, "can_see_flags": False}


def redact(player: Player) -> dict:
    """The fields that survive when a player is withheld.

    Enough to say a record exists and roughly who it is about, and nothing that identifies
    the child. No name, no date of birth, no external ids.
    """
    return {
        "id": player.id,
        "full_name": "Withheld",
        "known_as": None,
        "date_of_birth": None,
        "sex": player.sex,
        "nationality": [],
        "is_egypt_eligible": player.is_egypt_eligible,
        "primary_sport": player.primary_sport,
        "tier": player.tier,
        "position": player.position,
        "is_minor": player.is_minor,
        "status": player.status,
    }


def load_caller(db: Session, user: User) -> Caller:
    return Caller(
        user_id=user.id,
        role=user.role,
        organization_id=user.organization_id,
        linked_player_id=user.linked_player_id,
        full_name=user.full_name,
        email=user.email,
        organization_name=user.organization.name if user.organization else None,
    )
