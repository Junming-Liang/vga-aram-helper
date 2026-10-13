"""Process-local ONNX Runtime telemetry opt-out, before native initialization.

ORT 1.31.0's API can run after minimal 1DS initialization. Its documented
ORT_DISABLE_TELEMETRY=1 environment opt-out prevents the uploader, events and
persistent identifier from being created. Keep the API opt-out as well for
legacy providers. This is not a general-purpose network firewall.
Source: https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md
"""
import os


def disable_telemetry_before_import():
    # Deliberately override inherited opt-in: this app does not request telemetry.
    os.environ['ORT_DISABLE_TELEMETRY'] = '1'


def load_private_onnxruntime():
    disable_telemetry_before_import()
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    return onnxruntime


disable_telemetry_before_import()
