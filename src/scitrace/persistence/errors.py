"""Persistence 层对上暴露的稳定异常。"""


class PersistenceError(RuntimeError):
    """所有持久化错误的基类。"""


class EntityNotFoundError(PersistenceError):
    """按 ID 查询的实体不存在。"""


class EntityConflictError(PersistenceError):
    """同一稳定 ID 已对应不同内容，拒绝覆盖历史事实。"""


class InvalidLifecycleTransitionError(PersistenceError):
    """实体生命周期更新不符合业务不变量。"""
