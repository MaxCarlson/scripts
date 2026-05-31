"""drive_manager: cross-platform disk and USB management with safety-first dry runs."""

from .models import DiskInfo, PartitionInfo, VolumeInfo, UsbDiagnosis, OperationPlan, OperationResult

__all__ = [
    "DiskInfo",
    "PartitionInfo",
    "VolumeInfo",
    "UsbDiagnosis",
    "OperationPlan",
    "OperationResult",
]

__version__ = "0.2.0"
