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
0x04 ACK
0x05 ERROR

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
TYPE_ACK = 0x04
TYPE_ERROR = 0x05


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

    print("=== Test Finished ===")
