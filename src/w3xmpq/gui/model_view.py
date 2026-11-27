#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A small static 3D viewport for w3xmpq's model preview.

The widget consumes the Qt-free buffers from ``model_preview_data``. It is a
preview only: no animation, skinning, texture pixels or gameplay state. Mouse
left-drag orbits, wheel zooms, and right-drag pans.
"""

import array
import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .model_preview_data import empty_preview_mesh

VERTEX_SHADER = """
attribute vec3 aPosition;
attribute vec3 aNormal;
attribute vec4 aColor;
uniform mat4 uMvp;
varying vec3 vNormal;
varying vec4 vColor;
void main()
{
    vNormal = normalize(aNormal);
    vColor = aColor;
    gl_Position = uMvp * vec4(aPosition, 1.0);
}
"""

FRAGMENT_SHADER = """
varying vec3 vNormal;
varying vec4 vColor;
void main()
{
    vec3 light = normalize(vec3(0.35, -0.55, 0.75));
    float diffuse = max(dot(normalize(vNormal), light), 0.0);
    vec3 lit = vColor.rgb * (0.42 + 0.58 * diffuse);
    gl_FragColor = vec4(lit, vColor.a);
}
"""


class ModelView(QOpenGLWidget):
    """Render one bounded, static preview mesh."""

    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mesh = empty_preview_mesh()
        self.mode = "solid"
        self._program = None
        self._gl = None
        self._position = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._normal = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._colour = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._indices = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._wire = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
        self._locations = {}
        self._index_count = 0
        self._wire_count = 0
        self._last = None
        self._yaw = math.radians(35.0)
        self._pitch = math.radians(20.0)
        self._distance = 5.0
        self._target = QVector3D(0.0, 0.0, 0.0)
        self.setMinimumSize(220, 180)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self):
        return QSize(360, 260)

    # ------------------------------------------------------------- mesh
    def set_mesh(self, mesh):
        """Replace the displayed mesh and reset the camera around it."""
        self.mesh = mesh or empty_preview_mesh()
        self._reset_camera()
        if self._gl is not None:
            self._upload()
        self.update()

    def clear(self):
        self.set_mesh(empty_preview_mesh())

    def set_mode(self, mode):
        """Switch between ``solid`` and ``wire`` drawing."""
        self.mode = "wire" if mode == "wire" else "solid"
        self.update()

    def reset_view(self):
        self._reset_camera()
        self.update()

    def _reset_camera(self):
        center = self.mesh.get("center") or [0.0, 0.0, 0.0]
        self._target = QVector3D(float(center[0]), float(center[1]),
                                 float(center[2]))
        radius = float(self.mesh.get("radius") or 1.0)
        self._distance = max(radius * 2.6, 0.1)
        self._yaw = math.radians(35.0)
        self._pitch = math.radians(20.0)

    # --------------------------------------------------------------- GL
    def initializeGL(self):
        self._gl = self.context().functions()
        self._gl.glClearColor(0.07, 0.07, 0.08, 1.0)
        self._gl.glEnable(self._gl.GL_DEPTH_TEST)
        self._gl.glDisable(self._gl.GL_CULL_FACE)

        program = QOpenGLShaderProgram(self)
        if not program.addShaderFromSourceCode(QOpenGLShader.Vertex,
                                               VERTEX_SHADER):
            self.status.emit("3D preview: vertex shader failed to compile")
            return
        if not program.addShaderFromSourceCode(QOpenGLShader.Fragment,
                                               FRAGMENT_SHADER):
            self.status.emit("3D preview: fragment shader failed to compile")
            return
        if not program.link():
            self.status.emit("3D preview: shader link failed")
            return
        self._program = program
        self._locations = {
            "position": program.attributeLocation("aPosition"),
            "normal": program.attributeLocation("aNormal"),
            "colour": program.attributeLocation("aColor"),
            "mvp": program.uniformLocation("uMvp"),
        }
        self._upload()

    def _upload_buffer(self, buffer_obj, values, typecode):
        if buffer_obj.isCreated():
            buffer_obj.destroy()
        buffer_obj.create()
        if not values:
            return
        data = array.array(typecode, values)
        buffer_obj.bind()
        buffer_obj.allocate(data.tobytes(), len(data) * data.itemsize)
        buffer_obj.release()

    def _upload(self):
        if self._program is None:
            return
        self._upload_buffer(self._position, self.mesh.get("positions", []), "f")
        self._upload_buffer(self._normal, self.mesh.get("normals", []), "f")
        self._upload_buffer(self._colour, self.mesh.get("colors", []), "f")
        self._upload_buffer(self._indices, self.mesh.get("indices", []), "I")
        self._upload_buffer(self._wire, self.mesh.get("wire_indices", []), "I")
        self._index_count = len(self.mesh.get("indices", []))
        self._wire_count = len(self.mesh.get("wire_indices", []))

    def _bind_attribute(self, name, buffer_obj, tuple_size):
        location = self._locations.get(name, -1)
        if location < 0 or not buffer_obj.isCreated():
            return
        buffer_obj.bind()
        self._program.enableAttributeArray(location)
        self._program.setAttributeBuffer(location, self._gl.GL_FLOAT, 0,
                                         tuple_size, 0)
        buffer_obj.release()

    def resizeGL(self, width, height):
        if self._gl is not None:
            self._gl.glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self):
        if self._gl is None or self._program is None:
            return
        self._gl.glClear(self._gl.GL_COLOR_BUFFER_BIT |
                         self._gl.GL_DEPTH_BUFFER_BIT)

        width = max(1, self.width())
        height = max(1, self.height())
        cp = math.cos(self._pitch)
        camera = self._target + QVector3D(
            self._distance * cp * math.sin(self._yaw),
            self._distance * cp * math.cos(self._yaw),
            self._distance * math.sin(self._pitch))
        view = QMatrix4x4()
        view.lookAt(camera, self._target, QVector3D(0.0, 0.0, 1.0))
        radius = max(float(self.mesh.get("radius") or 1.0), 0.1)
        projection = QMatrix4x4()
        projection.perspective(45.0, width / float(height),
                               max(radius / 1000.0, 0.01),
                               max(radius * 100.0, self._distance * 4.0))

        self._program.bind()
        self._program.setUniformValue("uMvp", projection * view)
        self._bind_attribute("position", self._position, 3)
        self._bind_attribute("normal", self._normal, 3)
        self._bind_attribute("colour", self._colour, 4)

        if self.mode == "wire" and self._wire_count:
            self._wire.bind()
            self._gl.glDrawElements(self._gl.GL_LINES, self._wire_count,
                                    self._gl.GL_UNSIGNED_INT, None)
            self._wire.release()
        elif self._index_count:
            self._indices.bind()
            self._gl.glDrawElements(self._gl.GL_TRIANGLES, self._index_count,
                                    self._gl.GL_UNSIGNED_INT, None)
            self._indices.release()
        self._program.release()

    # ------------------------------------------------------------ input
    def mousePressEvent(self, event):
        self._last = event.position()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._last = None
        event.accept()

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        point = event.position()
        dx = point.x() - self._last.x()
        dy = point.y() - self._last.y()
        self._last = point
        if event.buttons() & Qt.LeftButton:
            self._yaw -= math.radians(dx * 0.5)
            self._pitch = max(-math.pi / 2.1,
                              min(math.pi / 2.1,
                                  self._pitch + math.radians(dy * 0.5)))
        elif event.buttons() & Qt.RightButton:
            scale = self._distance * 0.0025
            right = QVector3D(math.cos(self._yaw),
                              -math.sin(self._yaw), 0.0)
            up = QVector3D(-math.sin(self._yaw) * math.sin(self._pitch),
                           -math.cos(self._yaw) * math.sin(self._pitch),
                           math.cos(self._pitch))
            self._target -= right * dx * scale
            self._target += up * dy * scale
        self.update()
        event.accept()

    def wheelEvent(self, event):
        radius = max(float(self.mesh.get("radius") or 1.0), 0.1)
        factor = 1.15 if event.angleDelta().y() < 0 else 0.87
        self._distance = max(radius * 0.4,
                             min(radius * 20.0, self._distance * factor))
        self.update()
        event.accept()
