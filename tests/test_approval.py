from unittest.mock import patch

from hep_multiagent.features.human_in_loop import (
    AutoApproval, InterruptApproval, ApprovalResponse
)
from hep_multiagent.workers.compute import execute_python, set_code_approval


def test_auto_approval_approves_plan():
    approval = AutoApproval()
    plan = {"goal": "Test", "steps": []}
    response = approval.request_approval(plan)
    assert response.approved is True


def test_auto_approval_approves_code():
    approval = AutoApproval()
    response = approval.request_code_approval("print('hello')")
    assert response.approved is True


@patch("builtins.input", return_value="y")
def test_interrupt_approval_approves_plan_on_y(mock_input):
    approval = InterruptApproval()
    plan = {"goal": "Test", "steps": [{"name": "step1", "worker_type": "data", "description": "desc", "depends_on": []}]}
    response = approval.request_approval(plan)
    assert response.approved is True


@patch("builtins.input", return_value="n")
def test_interrupt_approval_rejects_plan_on_n(mock_input):
    approval = InterruptApproval()
    plan = {"goal": "Test", "steps": []}
    response = approval.request_approval(plan)
    assert response.approved is False


@patch("builtins.input", return_value="needs more detail")
def test_interrupt_approval_returns_feedback(mock_input):
    approval = InterruptApproval()
    plan = {"goal": "Test", "steps": []}
    response = approval.request_approval(plan)
    assert response.approved is False
    assert response.feedback == "needs more detail"


@patch("builtins.input", return_value="y")
def test_interrupt_approval_approves_code_on_y(mock_input):
    approval = InterruptApproval()
    response = approval.request_code_approval("print('hello')")
    assert response.approved is True


@patch("builtins.input", return_value="n")
def test_interrupt_approval_rejects_code_on_n(mock_input):
    approval = InterruptApproval()
    response = approval.request_code_approval("print('hello')")
    assert response.approved is False


def test_execute_python_no_approval_runs():
    set_code_approval(None)
    result = execute_python.invoke({"code": "print(1+1)"})
    assert "2" in result


def test_execute_python_auto_approval_runs():
    set_code_approval(AutoApproval())
    result = execute_python.invoke({"code": "print(2+2)"})
    assert "4" in result
    set_code_approval(None)


@patch("builtins.input", return_value="n")
def test_execute_python_rejected_returns_message(mock_input):
    set_code_approval(InterruptApproval())
    result = execute_python.invoke({"code": "print('should not run')"})
    assert "rejected" in result.lower()
    set_code_approval(None)


@patch("builtins.input", return_value="y")
def test_execute_python_approved_runs(mock_input):
    set_code_approval(InterruptApproval())
    result = execute_python.invoke({"code": "print(3+3)"})
    assert "6" in result
    set_code_approval(None)
