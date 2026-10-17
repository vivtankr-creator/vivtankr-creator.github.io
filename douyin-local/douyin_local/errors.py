class WorkflowError(Exception):
    """可向本地用户展示的固定错误。"""


class AuthRequired(WorkflowError):
    """需要用户在正常网站重新认证，禁止自动重试。"""
