"""可被多个 Tool 或应用服务复用的基础能力。"""

from scitrace.services.errors import (
    CandidateIdentityCollisionError,
    InvalidDiscoverySelectionError,
    ResourceObservationError,
)
from scitrace.services.resource import ResourceService
from scitrace.services.resource_admission import (
    ResourceAdmissionService,
    ResourceVerifier,
)

__all__ = [
    "CandidateIdentityCollisionError",
    "InvalidDiscoverySelectionError",
    "ResourceAdmissionService",
    "ResourceObservationError",
    "ResourceService",
    "ResourceVerifier",
]
