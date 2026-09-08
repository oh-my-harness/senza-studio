"""审批 + 通过后发通知邮件：checker → (approve) → send_email tool step。

比 approval_flow 多一步，展示组件真正的价值所在——批准之后"顺手发一封
通知邮件"是审批流里几乎必然要做的事，但手写要三步：加 checker、加 tool
step、把 tool 绑到 send_email 预制件并写对 tool_args。这里一次填好。

注意两个出口来自不同的内部 step：approve 出口挂在 _notify（邮件发完才
算走完批准这条路），reject 出口直接挂在 _review。preprocess 的 ports.exits
就是为这种情况设计的。

邮件发送依赖 SENZA_SMTP_* 配置（Studio 设置面板里的"邮件"分区）。没配的
话这一步会失败并走 error 路由，审批本身不受影响。
"""
from __future__ import annotations

COMPONENT: dict = {
    "name": "approval_with_notice",
    "keywords": ["审批", "人工审批", "审核", "批准", "邮件", "通知", "approval", "approve", "notify", "email"],
    "description": (
        "A human approval gate that also emails a notification when the "
        "request is approved. Pauses for a person to approve or reject, then "
        "on approval sends an email via SMTP before continuing. Wire it with "
        "next_on_approve and next_on_reject; optionally wire next_on_error to keep "
        "the workflow going when the email fails. Requires SENZA_SMTP_* settings."
    ),
    "params": {
        "title": {
            "type": "string",
            "description": "Shown to the approver as the prompt for this gate",
            "default": "请人工审批",
        },
        "notify_to": {
            "type": "string",
            "description": "Email address notified when the request is approved",
        },
        "notify_subject": {
            "type": "string",
            "description": "Subject of the approval notification email",
            "default": "审批已通过",
        },
        "notify_body": {
            "type": "string",
            "description": (
                "Body of the notification email. Supports {{context_var}} "
                "placeholders, which are filled from the run context."
            ),
            "default": "审批已通过。",
        },
    },
    "steps": [
        {
            "name": "{prefix}_review",
            "type": "checker",
            "message": "{title}",
            "ui": {"display": "approval_form"},
        },
        {
            "name": "{prefix}_notify",
            "type": "tool",
            "tool": "send_email",
            "tool_args": {
                "to": "{notify_to}",
                "subject": "{notify_subject}",
                "body": "{notify_body}",
            },
            "ui": {"display": "status"},
        },
    ],
    "edges": [
        {"from": "{prefix}_review", "to": "{prefix}_notify", "condition": "approve"},
    ],
    "ports": {
        "entry": "{prefix}_review",
        "exits": {
            # 批准这条路要等邮件发完才算走完，所以 approve 出口挂在 _notify
            # 而不是 _review——_review 的 approve 已经被内部边占用了。
            "approve": {"step": "{prefix}_notify", "condition": "success"},
            "reject": {"step": "{prefix}_review", "condition": "reject"},
            # 邮件发不出去时的兜底出口（可选）。不接的话整个 workflow 会以
            # "no route for 'error'" 失败——这是**故意**的默认行为：通知发
            # 失败了却当没事继续往下走，比直接失败更糟，至少要让人看见。
            # 但"通知失败不该挡住业务流程"也是合理的取舍，所以给一个显式的
            # 出口，让 spec 作者自己决定，而不是替他决定。
            "error": {"step": "{prefix}_notify", "condition": "error"},
        },
    },
}
