import numpy as np


class Joint:
    def __init__(self, joint_type, name="", axis=None, pivot=None, path=None, axisno=None, signal="", sprockets=None, loop=False):
        self.type = joint_type
        self.name = name

        self.axis = None
        if axis is not None:
            self.axis = np.array(axis, dtype=float)
            n = np.linalg.norm(self.axis)
            if n > 0:
                self.axis /= n

        self.pivot = np.array(pivot if pivot is not None else [0, 0, 0], dtype=float)
        self.path = path
        self.axisno = axisno
        self.signal = signal
        # chain 用
        self.sprockets: list[dict] | None = sprockets
        self.loop: bool = loop


class SceneNode:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.meshes = []

        self.local_T = np.eye(4)
        self.world_T = np.eye(4)
        self.def_T = np.eye(4)

        self.joint = None
        self.joint_value = 0.0