#!/usr/bin/env python3

"""
STM32 <-> RDK X5 通信协议

协议 V1.0

帧格式：

+--------+-----+------+-----+------+-------+
| SOF    | VER | TYPE | LEN | DATA | CRC16 |
| 2 byte | 1   | 1    | 2   | N    | 2     |
+--------+-----+------+-----+------+-------+

SOF  = 0xAA 0x55
VER  = 0x01

TYPE:
0x01 CMD_VEL
0x02 ENCODER
0x03 HEARTBEAT
0x04 IMU        与固件 stm32_firmware/applications/protocol.h 对齐
0x05 ERROR
0x06 ACK        原先是 0x04, 与固件 IMU 撞号, 现让位 (协议里暂无人用 ACK)

所有多字节整数采用 little-endian。
float32 使用 IEEE-754 little-endian。
"""

import struct
from dataclasses import dataclass


# ============================================================
# 协议基本参数
# ============================================================

SOF = b"\xAA\x55"
VERSION = 0x01

TYPE_CMD_VEL = 0x01
TYPE_ENCODER = 0x02
TYPE_HEARTBEAT = 0x03

# 0x04 在固件侧是 IMU:
#     #define PROTO_TYPE_IMU 0x04
# 上位机原先把 0x04 定义成 ACK, 于是下位机 10Hz 上报的 IMU 帧被当成 ACK
# 静默丢弃 —— 这就是 IMU 一直连不上的根因。现按固件对齐。
TYPE_IMU = 0x04
TYPE_ACK = 0x06          # 原 0x04, 让位给 IMU
TYPE_ERROR = 0x05

# IMU 载荷 (TYPE=0x04): ax,ay,az,gx,gy,gz 各 int32 LE,
# 物理量放大 1000 倍 —— 加速度 mg, 角速度 m°/s (见固件 proto_build_imu)
IMU_LEN = 24
IMU_FRAME_LEN = 2 + 1 + 1 + 2 + IMU_LEN + 2

# 单位换算: mg → m/s², m°/s → rad/s
MG_TO_MS2 = 9.80665 / 1000.0
MDPS_TO_RADS = 3.141592653589793 / 180000.0


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CmdVel:
    """
    RDK -> STM32

    vx: m/s
    vy: m/s
    omega: rad/s
    """

    vx: float
    vy: float
    omega: float


@dataclass
class EncoderData:
    """
    STM32 -> RDK

    timestamp_ms:
        STM32 时间戳，单位 ms

    fl:
        Front Left

    rl:
        Rear Left

    fr:
        Front Right

    rr:
        Rear Right

    encoder:
        编码器累计计数值
    """

    timestamp_ms: int
    fl: int
    rl: int
    fr: int
    rr: int


# ============================================================
# CRC16-CCITT
# ============================================================

def crc16_ccitt(data: bytes, crc: int = 0xFFFF) -> int:
    """
    CRC16-CCITT

    Polynomial:
        0x1021

    Initial:
        0xFFFF
    """

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


# ============================================================
# 帧打包
# ============================================================

def pack_frame(frame_type: int, data: bytes = b"") -> bytes:
    """
    将 TYPE + DATA 打包成完整通信帧。

    帧：

    AA 55
    VER
    TYPE
    LEN
    DATA
    CRC16
    """

    if not 0 <= frame_type <= 0xFF:
        raise ValueError("frame_type 必须是 0~255")

    if len(data) > 0xFFFF:
        raise ValueError("DATA 长度超过协议限制")

    header = struct.pack(
        "<BBH",
        VERSION,
        frame_type,
        len(data),
    )

    crc_data = header + data
    crc = crc16_ccitt(crc_data)

    return (
        SOF
        + crc_data
        + struct.pack("<H", crc)
    )


# ============================================================
# CMD_VEL
# ============================================================

def pack_cmd_vel(vx: float, vy: float, omega: float) -> bytes:
    """
    RDK -> STM32

    DATA:

    float32 vx
    float32 vy
    float32 omega

    单位：

    vx    m/s
    vy    m/s
    omega rad/s
    """

    data = struct.pack(
        "<fff",
        float(vx),
        float(vy),
        float(omega),
    )

    return pack_frame(TYPE_CMD_VEL, data)


def unpack_cmd_vel(data: bytes) -> CmdVel:
    """
    解析 CMD_VEL DATA。
    """

    if len(data) != 12:
        raise ValueError(
            f"CMD_VEL DATA 长度错误：{len(data)}，应为 12"
        )

    vx, vy, omega = struct.unpack("<fff", data)

    return CmdVel(
        vx=vx,
        vy=vy,
        omega=omega,
    )


# ============================================================
# ENCODER
# ============================================================

def pack_encoder(
    timestamp_ms: int,
    fl: int,
    rl: int,
    fr: int,
    rr: int,
) -> bytes:
    """
    STM32 -> RDK

    DATA:

    uint32 timestamp_ms
    int32  fl
    int32  rl
    int32  fr
    int32  rr

    总 DATA 长度 = 20 bytes
    """

    data = struct.pack(
        "<Iiiii",
        int(timestamp_ms),
        int(fl),
        int(rl),
        int(fr),
        int(rr),
    )

    return pack_frame(TYPE_ENCODER, data)


def unpack_encoder(data: bytes) -> EncoderData:
    """
    解析 ENCODER DATA。
    """

    if len(data) != 20:
        raise ValueError(
            f"ENCODER DATA 长度错误：{len(data)}，应为 20"
        )

    timestamp_ms, fl, rl, fr, rr = struct.unpack(
        "<Iiiii",
        data,
    )

    return EncoderData(
        timestamp_ms=timestamp_ms,
        fl=fl,
        rl=rl,
        fr=fr,
        rr=rr,
    )


# ============================================================
# IMU
# ============================================================

@dataclass
class ImuData:
    """
    STM32 -> RDK

    TYPE = 0x04, 载荷 24 字节, **不带时间戳** (帧里只有 6 个量测)。

    固件把物理量放大 1000 倍后以 int32 LE 发送:
        ax, ay, az : 加速度,  单位 mg   (毫 g)
        gx, gy, gz : 角速度,  单位 m°/s (毫度每秒)

    这里直接换算成 ROS/REP-103 习惯的 SI 单位:
        ax, ay, az : m/s²
        gx, gy, gz : rad/s
    """

    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


def pack_imu(ax_mg: int, ay_mg: int, az_mg: int,
             gx_mdps: int, gy_mdps: int, gz_mdps: int) -> bytes:
    """
    组一帧 IMU (TYPE=0x04)。

    入参是固件那边的**原始整数单位**: 加速度 mg、角速度 m°/s —— 保持与
    固件 proto_build_imu() 完全一致的字节布局, 供模拟器(fake_stm.py)和
    自测使用:
        AA 55 | 01 | 04 | 18 00 | ax ay az gx gy gz (int32 LE) | CRC16 LE
    """

    data = struct.pack(
        "<iiiiii",
        int(ax_mg),
        int(ay_mg),
        int(az_mg),
        int(gx_mdps),
        int(gy_mdps),
        int(gz_mdps),
    )

    return pack_frame(TYPE_IMU, data)


def unpack_imu(data: bytes) -> ImuData:
    """
    解析 IMU DATA(24 字节) → SI 单位 ImuData。
    """

    if len(data) != IMU_LEN:
        raise ValueError(f"IMU DATA 长度错误：{len(data)}，应为 {IMU_LEN}")

    ax, ay, az, gx, gy, gz = struct.unpack("<iiiiii", data)

    return ImuData(
        ax=ax * MG_TO_MS2,
        ay=ay * MG_TO_MS2,
        az=az * MG_TO_MS2,
        gx=gx * MDPS_TO_RADS,
        gy=gy * MDPS_TO_RADS,
        gz=gz * MDPS_TO_RADS,
    )


# ============================================================
# HEARTBEAT
# ============================================================

def pack_heartbeat(timestamp_ms: int) -> bytes:
    """
    心跳帧。

    DATA:

    uint32 timestamp_ms
    """

    data = struct.pack(
        "<I",
        int(timestamp_ms),
    )

    return pack_frame(TYPE_HEARTBEAT, data)


def unpack_heartbeat(data: bytes) -> int:
    """
    返回 heartbeat 时间戳。
    """

    if len(data) != 4:
        raise ValueError(
            f"HEARTBEAT DATA 长度错误：{len(data)}，应为 4"
        )

    return struct.unpack("<I", data)[0]


# ============================================================
# 通用帧解析器
# ============================================================

class FrameParser:
    """
    串口字节流解析器。

    串口数据可能出现：

    AA 55 ...
    AA 55 ...

    也可能一次 read() 收到半帧或者多帧。

    因此不能简单地“一次 read = 一帧”。

    FrameParser 会自动从字节流中寻找完整帧。
    """

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes):
        """
        输入新的串口数据。

        返回：

        [
            (frame_type, payload),
            ...
        ]
        """

        self.buffer.extend(data)

        frames = []

        while True:

            # ----------------------------------------
            # 1. 找帧头
            # ----------------------------------------

            sof_index = self.buffer.find(SOF)

            if sof_index < 0:

                # 没有找到 AA 55
                # 保留最后一个 AA，防止 AA 55 被拆开
                if self.buffer and self.buffer[-1] == 0xAA:
                    self.buffer = bytearray([0xAA])
                else:
                    self.buffer.clear()

                break

            # 丢弃帧头之前的无效数据
            if sof_index > 0:
                del self.buffer[:sof_index]

            # ----------------------------------------
            # 2. 判断是否已经拥有固定头部
            # ----------------------------------------

            # SOF(2) + VER(1) + TYPE(1) + LEN(2)
            if len(self.buffer) < 6:
                break

            version = self.buffer[2]
            frame_type = self.buffer[3]

            data_len = struct.unpack(
                "<H",
                self.buffer[4:6],
            )[0]

            # ----------------------------------------
            # 3. 检查协议版本
            # ----------------------------------------

            if version != VERSION:

                # 当前帧版本未知
                # 丢弃一个字节，重新寻找 SOF
                del self.buffer[0]
                continue

            # ----------------------------------------
            # 4. 计算完整帧长度
            # ----------------------------------------

            total_len = (
                2 +   # SOF
                1 +   # VERSION
                1 +   # TYPE
                2 +   # LEN
                data_len +
                2     # CRC16
            )

            if len(self.buffer) < total_len:
                break

            # ----------------------------------------
            # 5. 提取 DATA
            # ----------------------------------------

            frame = self.buffer[:total_len]

            payload_start = 6
            payload_end = 6 + data_len

            payload = bytes(
                frame[payload_start:payload_end]
            )

            # ----------------------------------------
            # 6. CRC 校验
            # ----------------------------------------

            received_crc = struct.unpack(
                "<H",
                frame[payload_end:payload_end + 2],
            )[0]

            calculated_crc = crc16_ccitt(
                bytes(frame[2:payload_end])
            )

            if received_crc != calculated_crc:

                # CRC 错误
                # 丢弃一个字节重新同步
                del self.buffer[0]
                continue

            # ----------------------------------------
            # 7. 成功解析
            # ----------------------------------------

            frames.append(
                (
                    frame_type,
                    payload,
                )
            )

            del self.buffer[:total_len]

        return frames


# ============================================================
# 简单自检
# ============================================================

if __name__ == "__main__":

    print("=== STM32 Bridge Protocol Test ===")

    # CMD_VEL
    frame = pack_cmd_vel(
        0.5,
        0.2,
        0.3,
    )

    print("CMD_VEL frame:")
    print(frame.hex(" "))

    parser = FrameParser()

    # 模拟串口分两次收到
    frames1 = parser.feed(frame[:5])
    frames2 = parser.feed(frame[5:])

    frames = frames1 + frames2

    print("Parsed frames:", frames)

    if frames:

        frame_type, payload = frames[0]

        print("TYPE:", hex(frame_type))

        cmd = unpack_cmd_vel(payload)

        print("vx =", cmd.vx)
        print("vy =", cmd.vy)
        print("omega =", cmd.omega)

    # IMU
    imu_frame = pack_imu(0, 0, 1000, 0, 0, 20000)

    print("IMU frame:")
    print(imu_frame.hex(" "))

    parser2 = FrameParser()

    parsed = parser2.feed(imu_frame)

    print("Parsed frames:", parsed)

    if parsed:

        ftype, payload = parsed[0]

        print("TYPE:", hex(ftype))

        imu = unpack_imu(payload)

        print("IMU:",
              "a =", (round(imu.ax, 3), round(imu.ay, 3), round(imu.az, 3)),
              "m/s²  g =", (round(imu.gx, 3), round(imu.gy, 3),
                            round(imu.gz, 3)), "rad/s")

    print("=== Test Finished ===")
