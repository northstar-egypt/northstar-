"""Diaspora submissions (decision 0011): submit a player abroad, see where it stands, and, for
federation staff, the verification queue. The rules are in app/services/submissions.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.submissions import (
    SubmissionConsentIn,
    SubmissionDecisionIn,
    SubmissionIn,
    SubmissionListOut,
    SubmissionOut,
)
from app.services import submissions
from app.services.access import Caller

router = APIRouter(tags=["submissions"], prefix="/submissions")


def _refused(exc: submissions.Rejected) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail={"message": "Nothing was saved.", "problems": exc.problems})


def _forbidden(what: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=what)


def require_submitter(caller: Caller = Depends(current_user)) -> Caller:
    if not submissions.may_submit(caller):
        raise _forbidden("Submissions are made by scouts, federation staff and players.")
    return caller


def require_reviewer(caller: Caller = Depends(current_user)) -> Caller:
    if not submissions.may_review(caller):
        raise _forbidden("The verification queue is limited to federation staff.")
    return caller


def _out(db: Session, caller: Caller, s) -> SubmissionOut:
    return SubmissionOut.model_validate(submissions.out(db, caller, s))


@router.post("", response_model=SubmissionOut, status_code=http_status.HTTP_201_CREATED)
def create_submission(payload: SubmissionIn, db: Session = Depends(get_db),
                      caller: Caller = Depends(require_submitter)) -> SubmissionOut:
    """Submit an Egypt-eligible player abroad. Checked on arrival; nothing becomes a player
    until federation staff approve it."""
    try:
        s = submissions.submit(db, caller, payload)
    except submissions.Rejected as exc:
        raise _refused(exc) from exc
    db.commit()
    return _out(db, caller, s)


@router.get("/mine", response_model=SubmissionListOut)
def my_submissions(db: Session = Depends(get_db), caller: Caller = Depends(require_submitter)) -> SubmissionListOut:
    return SubmissionListOut(submissions=[_out(db, caller, s) for s in submissions.mine(db, caller)])


@router.get("", response_model=SubmissionListOut)
def submission_queue(status: str | None = Query(default=None, description="e.g. approved; open ones by default"),
                     db: Session = Depends(get_db), caller: Caller = Depends(require_reviewer)) -> SubmissionListOut:
    """Open submissions, oldest first."""
    return SubmissionListOut(submissions=[_out(db, caller, s) for s in submissions.queue(db, caller, status)])


@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: uuid.UUID, db: Session = Depends(get_db),
                   caller: Caller = Depends(current_user)) -> SubmissionOut:
    try:
        return _out(db, caller, submissions.get(db, caller, submission_id))
    except submissions.NotFound:
        raise HTTPException(status_code=404, detail="No such submission.") from None


@router.put("/{submission_id}", response_model=SubmissionOut)
def update_submission(submission_id: uuid.UUID, payload: SubmissionIn, db: Session = Depends(get_db),
                      caller: Caller = Depends(require_submitter)) -> SubmissionOut:
    """The submitter's edit, while it is open. It is checked again and is pending again."""
    try:
        s = submissions.update(db, caller, submission_id, payload)
    except submissions.NotFound:
        raise HTTPException(status_code=404, detail="No such submission.") from None
    except submissions.Forbidden:
        raise _forbidden("Only the submitter can change a submission.") from None
    except submissions.Rejected as exc:
        raise _refused(exc) from exc
    db.commit()
    return _out(db, caller, s)


@router.post("/{submission_id}/consent", response_model=SubmissionOut)
def record_consent(submission_id: uuid.UUID, form: SubmissionConsentIn, db: Session = Depends(get_db),
                   caller: Caller = Depends(require_reviewer)) -> SubmissionOut:
    """Record the signed consent form for a submission that waits for it."""
    try:
        s = submissions.record_consent(db, caller, submission_id, form)
    except submissions.NotFound:
        raise HTTPException(status_code=404, detail="No such submission.") from None
    except submissions.Rejected as exc:
        raise _refused(exc) from exc
    db.commit()
    return _out(db, caller, s)


@router.post("/{submission_id}/decision", response_model=SubmissionOut)
def decide(submission_id: uuid.UUID, decision: SubmissionDecisionIn, db: Session = Depends(get_db),
           caller: Caller = Depends(require_reviewer)) -> SubmissionOut:
    """approve (a new player), attach (the same person as `playerId`), reject, or needs_info.
    Every decision has a reason, which the submitter sees."""
    try:
        s = submissions.decide(db, caller, submission_id, decision)
    except submissions.NotFound:
        raise HTTPException(status_code=404, detail="No such submission.") from None
    except submissions.Forbidden:
        raise _forbidden("A reviewer cannot decide their own submission.") from None
    except submissions.Rejected as exc:
        raise _refused(exc) from exc
    db.commit()
    return _out(db, caller, s)
