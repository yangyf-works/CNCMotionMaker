# CNCMotionMaker

An open-source CNC machine motion visualization and Digital Twin platform built with Open3D.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Open3D](https://img.shields.io/badge/Open3D-0.19-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

<p align="center">
  <img src="docs/images/main.png" alt="CNCMotionMaker Main Window" width="900">
</p>

## Overview

CNCMotionMaker is an open-source desktop application for visualizing CNC machine motion.

Machine structures are defined in JSON and rendered using Open3D.

The project focuses on machine visualization, Digital Twin development, and future CNC simulation.

## Features

- JSON-based machine definition
- Hierarchical machine structure
- Linear / Rotary / Signal / Chain joints
- Multi-window Open3D viewer
- NC Program playback
- Joint axis visualization
- Camera tracking
- STL export
- Digital Twin interface

## Installation

```bash
git clone ...

cd CNCMotionMaker

pip install -r requirements.txt

python main.py
```
## License

MIT License