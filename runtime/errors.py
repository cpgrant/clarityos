class PolicyDeniedError(PermissionError):
    def __init__(self, message: str, *, capability: str, policy_name: str) -> None:
        super().__init__(message)
        self.capability = capability
        self.policy_name = policy_name


class DelegationDeniedError(PermissionError):
    def __init__(self, message: str, *, capability: str, workflow_id: str) -> None:
        super().__init__(message)
        self.capability = capability
        self.workflow_id = workflow_id


class BudgetExceededError(RuntimeError):
    def __init__(self, message: str, *, budget_name: str) -> None:
        super().__init__(message)
        self.budget_name = budget_name


class ApprovalStateError(RuntimeError):
    def __init__(self, message: str, *, approval_id: str) -> None:
        super().__init__(message)
        self.approval_id = approval_id


class OperatorAuthError(PermissionError):
    def __init__(self, message: str, *, header_name: str) -> None:
        super().__init__(message)
        self.header_name = header_name
