from .extension import QualisysMocapExtension as construct

__all__ = ("construct",)

description = "Connection to Qualisys motion capture systems"
dependencies = ("motion_capture",)
tags = ("experimental",)
schema = {
    "properties": {
        "connection": {
            "type": "string",
            "title": "Connection URL",
            "description": (
                "Use tcp://hostname:22223 to connect to Qualisys Track Manager "
                "running on the given host with the given base port."
            ),
            "default": "tcp://localhost:22223",
        }
    }
}
