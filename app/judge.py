"""Person B evidence-only judgment interface."""
from .schemas import Judgment,VerdictLabel
def judge_claim(claim,evidence,provider=None):
    if not claim.checkable:return Judgment(claim_id=claim.id or "",label=VerdictLabel.UNVERIFIABLE,confidence="High",rationale="This is a non-checkable statement such as a prediction, opinion, or testimonial.")
    if not evidence:return Judgment(claim_id=claim.id or "",label=VerdictLabel.NO_EVIDENCE,confidence="High",rationale="No relevant evidence was retrieved for this claim.")
    return None,"not_implemented"
