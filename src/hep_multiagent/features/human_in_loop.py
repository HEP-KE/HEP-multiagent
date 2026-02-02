from dataclasses import dataclass
from typing import Optional

from ..state import Plan


@dataclass
class ApprovalResponse:
    approved: bool
    feedback: Optional[str] = None


def format_plan_preview(plan: Plan) -> str:
    lines = [
        "# Proposed Plan",
        "",
        f"**Goal:** {plan['goal']}",
        "",
        "## Steps:",
        "",
    ]

    for i, step in enumerate(plan["steps"], 1):
        deps = ""
        if step["depends_on"]:
            dep_names = []
            for dep_id in step["depends_on"]:
                for s in plan["steps"]:
                    if s["id"] == dep_id:
                        dep_names.append(s["name"])
                        break
            if dep_names:
                deps = f" (after: {', '.join(dep_names)})"

        lines.append(f"{i}. **{step['name']}** [{step['worker_type']}]{deps}")
        lines.append(f"   {step['description']}")
        lines.append("")

    return "\n".join(lines)


class AutoApproval:
    def request_approval(self, plan: Plan) -> ApprovalResponse:
        return ApprovalResponse(approved=True)


class InterruptApproval:
    def request_approval(self, plan: Plan) -> ApprovalResponse:
        preview = format_plan_preview(plan)

        print("\n" + "=" * 50)
        print("PLAN APPROVAL REQUIRED")
        print("=" * 50)
        print(preview)
        print("=" * 50)

        response = input("Approve? [y/n/feedback]: ").strip().lower()

        if response == "y":
            return ApprovalResponse(approved=True)
        elif response == "n":
            return ApprovalResponse(approved=False)
        else:
            return ApprovalResponse(approved=False, feedback=response)
