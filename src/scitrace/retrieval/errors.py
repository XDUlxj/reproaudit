"""Ingestion 与 Retrieval 的稳定错误类型。"""


class RetrievalInfrastructureError(RuntimeError):
    """检索基础设施错误基类。"""


class UnsupportedResourceError(RetrievalInfrastructureError):
    """当前版本不支持该资源类型或内容格式。"""


class ResourceResolutionError(RetrievalInfrastructureError):
    """无法把资源定位为可读取的固定原始内容。"""


class InvalidRetrievalRequestError(RetrievalInfrastructureError):
    """检索请求缺少必要范围或参数不合法。"""
