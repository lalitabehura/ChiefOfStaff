from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AutomationRule, User
from app.schemas import RuleIn, RuleOut

router = APIRouter(prefix="/rules", tags=["rules"])
MAX_RULES = 50


def _owned(db: Session, user: User, rule_id: str) -> AutomationRule:
    r = db.get(AutomationRule, rule_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return r


@router.get("", response_model=list[RuleOut])
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(AutomationRule).where(AutomationRule.user_id == user.id)
                      .order_by(AutomationRule.created_at)).all()


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(AutomationRule).where(AutomationRule.user_id == user.id))
    if count >= MAX_RULES:
        raise HTTPException(status_code=400, detail=f"Maximum of {MAX_RULES} rules.")
    rule = AutomationRule(user_id=user.id, name=body.name, trigger=body.trigger,
                          conditions=body.conditions.model_dump(exclude_none=True),
                          action=body.action.model_dump(exclude_none=True),
                          autonomy=body.autonomy, enabled=body.enabled)
    db.add(rule)
    db.commit()
    return rule


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rule = _owned(db, user, rule_id)
    rule.name, rule.trigger, rule.autonomy, rule.enabled = body.name, body.trigger, body.autonomy, body.enabled
    rule.conditions = body.conditions.model_dump(exclude_none=True)
    rule.action = body.action.model_dump(exclude_none=True)
    db.commit()
    return rule


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, user, rule_id))
    db.commit()
