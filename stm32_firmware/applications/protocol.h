/*
 * 上位机通信协议 V1.0 (STM32 <-> RDK X5)
 *
 * 帧格式: AA 55 | VER | TYPE | LEN(2,LE) | DATA | CRC16(2,LE)
 *         SOF    0x01   ...     长度        载荷   覆盖 VER..DATA
 * CRC16-CCITT: poly 0x1021, init 0xFFFF
 */

#ifndef __PROTOCOL_H__
#define __PROTOCOL_H__

#include <rtthread.h>

#define PROTO_SOF0              0xAA
#define PROTO_SOF1              0x55
#define PROTO_VER               0x01

#define PROTO_TYPE_CMD_VEL      0x01
#define PROTO_TYPE_ENCODER      0x02
#define PROTO_TYPE_HEARTBEAT    0x03
#define PROTO_TYPE_IMU          0x04

#define PROTO_CMD_VEL_LEN       12
#define PROTO_ENCODER_LEN       20
#define PROTO_IMU_LEN           24

/* SOF(2) + VER(1) + TYPE(1) + LEN(2) + DATA(20) + CRC(2) */
#define PROTO_ENCODER_FRAME_LEN (2 + 1 + 1 + 2 + PROTO_ENCODER_LEN + 2)

/* SOF(2) + VER(1) + TYPE(1) + LEN(2) + DATA(24) + CRC(2) */
#define PROTO_IMU_FRAME_LEN     (2 + 1 + 1 + 2 + PROTO_IMU_LEN + 2)

uint16_t proto_crc16(const uint8_t *data, rt_size_t len, uint16_t seed);

/* 组包一帧 ENCODER(TYPE=0x02): timestamp_ms + FL,RL,FR,RR 累计脉冲
 * 返回帧总长度, frame 缓冲区至少 PROTO_ENCODER_FRAME_LEN 字节 */
rt_size_t proto_build_encoder(uint8_t *frame, rt_uint32_t timestamp_ms, const rt_int32_t counts[4]);

/* 组包一帧 IMU(TYPE=0x04): ax,ay,az,gx,gy,gz, 各 int32 LE, 物理量放大 1000 倍
 * (加速度单位 mg, 陀螺单位 m°/s). 返回帧总长度, frame 缓冲区至少 PROTO_IMU_FRAME_LEN 字节 */
rt_size_t proto_build_imu(uint8_t *frame, const rt_int32_t imu[6]);

/* CMD_VEL(TYPE=0x01) 回调: vx(m/s), vy(m/s), omega(rad/s) */
typedef void (*proto_vel_cb_t)(float vx, float vy, float omega);
void proto_set_vel_callback(proto_vel_cb_t cb);

void proto_reset(void);
void proto_feed(const uint8_t *data, rt_size_t len);

#endif /* __PROTOCOL_H__ */
