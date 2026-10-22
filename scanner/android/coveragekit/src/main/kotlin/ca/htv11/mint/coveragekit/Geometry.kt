package ca.htv11.mint.coveragekit

import kotlin.math.sqrt

/** A 3-vector (metres or directions). */
data class Vec3(val x: Float, val y: Float, val z: Float) {
    operator fun plus(o: Vec3) = Vec3(x + o.x, y + o.y, z + o.z)
    operator fun minus(o: Vec3) = Vec3(x - o.x, y - o.y, z - o.z)
    operator fun times(s: Float) = Vec3(x * s, y * s, z * s)
    operator fun unaryMinus() = Vec3(-x, -y, -z)
    infix fun dot(o: Vec3) = x * o.x + y * o.y + z * o.z
    infix fun cross(o: Vec3) = Vec3(y * o.z - z * o.y, z * o.x - x * o.z, x * o.y - y * o.x)
    val length: Float get() = sqrt(this dot this)
    fun normalized(): Vec3 = this * (1f / length)
}

/**
 * A 3×3 matrix, column-major like ARCore's `Pose.toMatrix` and ARKit's simd (`m[c * 3 + r]`).
 * Used for the camera's rotation, camera → world.
 */
class Mat3(private val m: FloatArray) {
    init { require(m.size == 9) }

    operator fun get(row: Int, col: Int): Float = m[col * 3 + row]

    operator fun times(v: Vec3) = Vec3(
        this[0, 0] * v.x + this[0, 1] * v.y + this[0, 2] * v.z,
        this[1, 0] * v.x + this[1, 1] * v.y + this[1, 2] * v.z,
        this[2, 0] * v.x + this[2, 1] * v.y + this[2, 2] * v.z,
    )

    companion object {
        /** The rotation part of a column-major 4×4 (`Pose.toMatrix`). */
        fun rotationOf(m4: FloatArray): Mat3 {
            require(m4.size == 16)
            return Mat3(floatArrayOf(m4[0], m4[1], m4[2], m4[4], m4[5], m4[6], m4[8], m4[9], m4[10]))
        }
    }
}

/** Camera intrinsics: focal lengths and principal point in pixels of one image. */
data class CameraK(val fx: Float, val fy: Float, val cx: Float, val cy: Float) {
    /** The 3×3 K, row-major (the contract's mat3). */
    fun rowMajor(): List<List<Double>> = listOf(
        listOf(fx.toDouble(), 0.0, cx.toDouble()),
        listOf(0.0, fy.toDouble(), cy.toDouble()),
        listOf(0.0, 0.0, 1.0),
    )

    /** Scale to a resized image (D2: K must match the saved pixels). Pixel-corner convention: cx, cy scale linearly. */
    fun scaled(sx: Float, sy: Float) = CameraK(fx * sx, fy * sy, cx * sx, cy * sy)
}

object Geometry {
    /** Row-major nested lists (the contract's mat4) from a column-major 4×4 (`Pose.toMatrix`): transposes. */
    fun rowMajor4(m: FloatArray): List<List<Double>> {
        require(m.size == 16)
        return (0 until 4).map { r -> (0 until 4).map { c -> m[c * 4 + r].toDouble() } }
    }
}
