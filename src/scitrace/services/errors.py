"""Resource discovery/admission 的轻量契约异常。"""


class InvalidDiscoverySelectionError(RuntimeError):
    """DiscoverySelection 引用了本轮未观察到的 Candidate 或 Resource。"""


class ResourceObservationError(RuntimeError):
    """Candidate-producing Tool 违反了 ResourceCandidate 输出契约。"""
