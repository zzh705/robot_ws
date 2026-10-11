#include "protocol.h"
#include <string.h>

/* 接收状态机 */
enum
{
    PS_SOF0 = 0,
    PS_SOF1,
    PS_VER,
    PS_TYPE,
    PS_LEN0,
    PS_LEN1,
    PS_DATA,
    PS_CRC0,
    PS_CRC1,
};

#define PROTO_MAX_PAYLOAD   32

static rt_uint8_t    s_state = PS_SOF0;
static rt_uint8_t    s_type;
static rt_uint16_t   s_len;
static rt_uint16_t   s_idx;
static rt_uint8_t    s_payload[PROTO_MAX_PAYLOAD];
static rt_uint8_t    s_crc_lo;
static proto_vel_cb_t s_vel_cb = RT_NULL;

uint16_t proto_crc16(const uint8_t *data, rt_size_t len, uint16_t seed)
{
    uint16_t crc = seed;

    for (rt_size_t i = 0; i < len; i++)
    {
        crc ^= (uint16_t)data[i] << 8;
        for (int j = 0; j < 8; j++)
        {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021)
                                 : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

static void put_u32_le(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

static float get_f32_le(const uint8_t *p)
{
    uint32_t u = (uint32_t)p[0]
               | ((uint32_t)p[1] << 8)
               | ((uint32_t)p[2] << 16)
               | ((uint32_t)p[3] << 24);
    float f;
    memcpy(&f, &u, sizeof(f));
    return f;
}

rt_size_t proto_build_encoder(uint8_t *frame, rt_uint32_t timestamp_ms, const rt_int32_t counts[4])
{
    const uint16_t len = PROTO_ENCODER_LEN;
    uint16_t crc;

    frame[0] = PROTO_SOF0;
    frame[1] = PROTO_SOF1;
    frame[2] = PROTO_VER;
    frame[3] = PROTO_TYPE_ENCODER;
    frame[4] = (uint8_t)(len & 0xFF);
    frame[5] = (uint8_t)(len >> 8);

    put_u32_le(&frame[6], timestamp_ms);
    for (int i = 0; i < 4; i++)
    {
        put_u32_le(&frame[6 + 4 + i * 4], (uint32_t)counts[i]);
    }

    /* CRC 覆盖 VER..DATA 末尾, 共 4 + len 字节 */
    crc = proto_crc16(&frame[2], (rt_size_t)(4 + len), 0xFFFF);
    frame[6 + len] = (uint8_t)(crc & 0xFF);
    frame[7 + len] = (uint8_t)(crc >> 8);

    return PROTO_ENCODER_FRAME_LEN;
}

rt_size_t proto_build_imu(uint8_t *frame, const rt_int32_t imu[6])
{
    const uint16_t len = PROTO_IMU_LEN;
    uint16_t crc;

    frame[0] = PROTO_SOF0;
    frame[1] = PROTO_SOF1;
    frame[2] = PROTO_VER;
    frame[3] = PROTO_TYPE_IMU;
    frame[4] = (uint8_t)(len & 0xFF);
    frame[5] = (uint8_t)(len >> 8);

    for (int i = 0; i < 6; i++)
    {
        put_u32_le(&frame[6 + i * 4], (uint32_t)imu[i]);
    }

    /* CRC 覆盖 VER..DATA 末尾, 共 4 + len 字节 */
    crc = proto_crc16(&frame[2], (rt_size_t)(4 + len), 0xFFFF);
    frame[6 + len] = (uint8_t)(crc & 0xFF);
    frame[7 + len] = (uint8_t)(crc >> 8);

    return PROTO_IMU_FRAME_LEN;
}

static void proto_dispatch(void)
{
    if (s_type == PROTO_TYPE_CMD_VEL && s_len == PROTO_CMD_VEL_LEN && s_vel_cb != RT_NULL)
    {
        float vx = get_f32_le(&s_payload[0]);
        float vy = get_f32_le(&s_payload[4]);
        float omega = get_f32_le(&s_payload[8]);
        s_vel_cb(vx, vy, omega);
    }
}

void proto_set_vel_callback(proto_vel_cb_t cb)
{
    s_vel_cb = cb;
}

void proto_reset(void)
{
    s_state = PS_SOF0;
    s_type = 0;
    s_len = 0;
    s_idx = 0;
}

void proto_feed(const uint8_t *data, rt_size_t len)
{
    for (rt_size_t i = 0; i < len; i++)
    {
        uint8_t b = data[i];

        switch (s_state)
        {
        case PS_SOF0:
            if (b == PROTO_SOF0) s_state = PS_SOF1;
            break;

        case PS_SOF1:
            s_state = (b == PROTO_SOF1) ? PS_VER : PS_SOF0;
            break;

        case PS_VER:
            s_state = (b == PROTO_VER) ? PS_TYPE : PS_SOF0;
            break;

        case PS_TYPE:
            s_type = b;
            s_state = PS_LEN0;
            break;

        case PS_LEN0:
            s_len = b;
            s_state = PS_LEN1;
            break;

        case PS_LEN1:
            s_len |= (uint16_t)b << 8;
            if (s_len > PROTO_MAX_PAYLOAD)
            {
                s_state = PS_SOF0;
            }
            else if (s_len == 0)
            {
                s_idx = 0;
                s_state = PS_CRC0;
            }
            else
            {
                s_idx = 0;
                s_state = PS_DATA;
            }
            break;

        case PS_DATA:
            s_payload[s_idx++] = b;
            if (s_idx >= s_len) s_state = PS_CRC0;
            break;

        case PS_CRC0:
            s_crc_lo = b;
            s_state = PS_CRC1;
            break;

        case PS_CRC1:
        {
            uint8_t check[4 + PROTO_MAX_PAYLOAD];
            uint16_t rx = (uint16_t)(s_crc_lo | ((uint16_t)b << 8));

            check[0] = PROTO_VER;
            check[1] = s_type;
            check[2] = (uint8_t)(s_len & 0xFF);
            check[3] = (uint8_t)(s_len >> 8);
            memcpy(&check[4], s_payload, s_len);

            if (proto_crc16(check, (rt_size_t)(4 + s_len), 0xFFFF) == rx)
            {
                proto_dispatch();
            }
            s_state = PS_SOF0;
            break;
        }

        default:
            s_state = PS_SOF0;
            break;
        }
    }
}
