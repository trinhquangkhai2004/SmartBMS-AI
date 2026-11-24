"""Research authorization is bound to the reviewed artifact and this execution scope."""
from hashlib import sha256
import json
from pathlib import Path


ECM_SHA = "4105b629aad216ec88de49084c629a14359537dbd670a65a6d79be93fbfffa34"
APPROVAL_ID = "PBL5-SOC-20261119-RESEARCH"


def require_conditional_approval(root, milestone):
    root = Path(root)
    receipt = json.loads((root / "approvals/conditional_approval_record.json").read_text("utf-8"))
    policy = json.loads((root / "configs/g10_conditional_run_policy.yaml").read_text("utf-8"))
    if not (receipt["decision"] == "APPROVED_CONDITIONAL"
            and receipt["conditional_execution_allowed"] is True
            and milestone in receipt["scope"] and milestone in ("P2.4", "P2.5")
            and receipt["approval_source"] and receipt["approved_by"]
            and receipt["approval_record_id"] == policy["approval_record_id"] == APPROVAL_ID
            and receipt["scientific_release"] is policy["scientific_release"] is False
            and receipt["ecm_sha256"] == policy["ecm_sha256"] == ECM_SHA
            and policy["warning_threshold_v"] == 3.2976):
        raise PermissionError("Conditional research scope or policy mismatch")
    data = (root / "artifacts/ecm_params.json").read_bytes()
    if sha256(data).hexdigest() != ECM_SHA or json.loads(data)["lock_status"] != "NEEDS_REVIEW_NOT_RELEASED":
        raise ValueError("Frozen candidate identity mismatch")
    return receipt
