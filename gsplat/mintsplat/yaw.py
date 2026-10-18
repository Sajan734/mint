import math


def yaw_deg(matrix) -> float:
    """The turn about +Y, in degrees, of the buyer agent's alignment (row-major 4x4, buyer scan -> listing scan,
    multiagent/buyer_agent/align.py; the upright fit only turns about +Y, and may scale).

    The website shows the buyer's splat with mesh.rotation.y = this angle (lib/splat-scene.ts fragmentRotation,
    '#ry=<deg>'). three.js turns by R_y(t) = [[cos t, 0, sin t], [0, 1, 0], [-sin t, 0, cos t]], so t is read from
    the matrix's first row; a uniform scale cancels in atan2."""
    return math.degrees(math.atan2(float(matrix[0][2]), float(matrix[0][0])))
