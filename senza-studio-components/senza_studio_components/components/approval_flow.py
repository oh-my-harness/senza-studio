"""人工审批门：一个 checker step，approve/reject 两个出口。

最小的能力组件——只有一个内部 step。存在的意义不是"省了一个 add_step"，
而是把"审批门长什么样"这件事固定下来：type 必须是 checker、ui.display
必须是 approval_form、出口必须叫 approve/reject（Studio 的 submit_decision
把人工决定原样当 route_key 用，见 play.py 的 checker 分支）。这几件事任何
一个写错，Play 到这一步就会挂在路由失败上，而组件让它没法写错。
"""
from __future__ import annotations

COMPONENT: dict = {
    "name": "approval_flow",
    "keywords": ["审批", "人工审批", "审核", "批准", "驳回", "approval", "approve", "human"],
    "description": (
        "A human approval gate. Pauses the run and waits for a person to "
        "approve or reject in the Studio UI, then routes to a different next "
        "step depending on the decision. Wire it with next_on_approve and "
        "next_on_reject."
    ),
    "params": {
        "title": {
            "type": "string",
            "description": "Shown to the approver as the prompt for this gate",
            "default": "请人工审批",
        },
    },
    "steps": [
        {
            "name": "{prefix}_review",
            "type": "checker",
            "message": "{title}",
            "ui": {"display": "approval_form"},
        },
    ],
    "edges": [],
    "ports": {
        "entry": "{prefix}_review",
        "exits": {
            "approve": {"step": "{prefix}_review", "condition": "approve"},
            "reject": {"step": "{prefix}_review", "condition": "reject"},
        },
    },
}
