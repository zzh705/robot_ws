#include <rtthread.h>
#include <rtdevice.h>
#include <string.h>
#include "pwm_test.h"
#include "pulse.h"
#include "motion_ctrl.h"
#include "protocol.h"

/* 上位机通信串口: UART3(PD8/PD9) -> 板载 CH9102F(U7) -> USB-COM 口 */
#define UPPER_UART_DEV          "uart3"

/* ENCODER 上报周期 20ms = 50Hz */
#define ENC_REPORT_PERIOD_MS    20

/* 超过该时间未收到 CMD_VEL 则自动停车 */
#define CMD_TIMEOUT_MS          500

/* 上位机速度单位 m/s -> 轮速 cm/s */
#define CMD_VEL_MPS_TO_CMPS     100.0f

/* 单轮指令速度上限(cm/s), 安全限幅 */
#define WHEEL_CMD_LIMIT_CM      100.0f

/* IMU 数据上报总开关(强制类型转换, 线程间共享) */
volatile rt_bool_t g_send_mpu_data = RT_TRUE;

static rt_device_t g_upper_uart = RT_NULL;
static rt_mutex_t  g_uart_tx_mutex = RT_NULL;  /* 串行化 uart3 多线程发送 */
static rt_sem_t g_rx_sem = RT_NULL;
static volatile rt_tick_t g_last_cmd_tick = 0;

static float clamp_wheel_cmd(float v)
{
    if (v > WHEEL_CMD_LIMIT_CM) return WHEEL_CMD_LIMIT_CM;
    if (v < -WHEEL_CMD_LIMIT_CM) return -WHEEL_CMD_LIMIT_CM;
    return v;
}

/* 向 uart3 发送一帧(带互斥保护), 供多线程(编码器/IMU)共用 */
rt_err_t upper_uart_send(const uint8_t *data, rt_size_t len)
{
    if (g_upper_uart == RT_NULL)
    {
        return -RT_ERROR;
    }
    if (g_uart_tx_mutex != RT_NULL)
    {
        rt_mutex_take(g_uart_tx_mutex, RT_WAITING_FOREVER);
    }
    rt_err_t result = rt_device_write(g_upper_uart, 0, data, len);
    if (g_uart_tx_mutex != RT_NULL)
    {
        rt_mutex_release(g_uart_tx_mutex);
    }
    return result;
}

/* CMD_VEL(TYPE=0x01) 回调: vx/vy(m/s), omega(rad/s) */
static void on_cmd_vel(float vx, float vy, float omega)
{
    float v1, v2, v3, v4;

    g_last_cmd_tick = rt_tick_get();

    mecanum_calc(vx * CMD_VEL_MPS_TO_CMPS,
                 vy * CMD_VEL_MPS_TO_CMPS,
                 omega,
                 &v1, &v2, &v3, &v4);

    motion_request_wheels(clamp_wheel_cmd(v1),
                          clamp_wheel_cmd(v2),
                          clamp_wheel_cmd(v3),
                          clamp_wheel_cmd(v4));
}

/* 串口接收中断回调：只释放信号量，不在中断上下文做协议解析/PID/加锁 */
static rt_err_t uart_rx_ind(rt_device_t dev, rt_size_t size)
{
    RT_UNUSED(dev);
    RT_UNUSED(size);
    if (g_rx_sem != RT_NULL)
    {
        rt_sem_release(g_rx_sem);
    }
    return RT_EOK;
}

/* 线程上下文解析上位机指令（可安全获取互斥锁） */
static void uart_rx_thread(void *parameter)
{
    uint8_t ch;

    RT_UNUSED(parameter);

    while (1)
    {
        rt_sem_take(g_rx_sem, RT_WAITING_FOREVER);

        while (g_upper_uart != RT_NULL &&
               rt_device_read(g_upper_uart, 0, &ch, 1) == 1)
        {
            proto_feed(&ch, 1);
        }
    }
}

/* 20ms 周期上报编码器累计脉冲 + 指令超时停车 */
static void encoder_report_thread(void *parameter)
{
    uint8_t frame[PROTO_ENCODER_FRAME_LEN];
    rt_int32_t counts[4];

    RT_UNUSED(parameter);

    while (1)
    {
        pulse_get_raw_counts(counts);
        rt_size_t n = proto_build_encoder(frame, (rt_uint32_t)rt_tick_get(), counts);
        upper_uart_send(frame, n);

        if (g_last_cmd_tick != 0 &&
            (rt_tick_get() - g_last_cmd_tick) > CMD_TIMEOUT_MS)
        {
            motion_request_wheels(0, 0, 0, 0);
            g_last_cmd_tick = 0;
        }

        rt_thread_mdelay(ENC_REPORT_PERIOD_MS);
    }
}

int main(void)
{
    rt_kprintf("===== Car Control System Start =====\n");

    motion_ctrl_init();

    proto_set_vel_callback(on_cmd_vel);

    g_rx_sem = rt_sem_create("rx_sem", 0, RT_IPC_FLAG_FIFO);
    if (g_rx_sem == RT_NULL)
    {
        rt_kprintf("[ERR] Failed to create rx semaphore\n");
        return -RT_ERROR;
    }

    g_uart_tx_mutex = rt_mutex_create("uart_tx", RT_IPC_FLAG_FIFO);
    if (g_uart_tx_mutex == RT_NULL)
    {
        rt_kprintf("[ERR] Failed to create uart tx mutex\n");
        return -RT_ERROR;
    }

    g_upper_uart = rt_device_find(UPPER_UART_DEV);
    if (g_upper_uart)
    {
        struct serial_configure uart_cfg = RT_SERIAL_CONFIG_DEFAULT;
        uart_cfg.baud_rate = BAUD_RATE_115200;
        uart_cfg.data_bits = DATA_BITS_8;
        uart_cfg.stop_bits = STOP_BITS_1;
        uart_cfg.parity    = PARITY_NONE;

        rt_device_control(g_upper_uart, RT_DEVICE_CTRL_CONFIG, &uart_cfg);
        rt_device_open(g_upper_uart, RT_DEVICE_FLAG_RDWR | RT_DEVICE_FLAG_INT_RX);
        rt_device_set_rx_indicate(g_upper_uart, uart_rx_ind);
        rt_kprintf("[SYS] UART3 (PD8/PD9) opened for upper computer at 115200 8N1\n");
    }
    else
    {
        rt_kprintf("[ERR] UART3 device not found\n");
    }

    rt_thread_t rx_thread = rt_thread_create("uart_rx", uart_rx_thread,
                                             RT_NULL, 1024, 7, 10);
    if (rx_thread) rt_thread_startup(rx_thread);
    else rt_kprintf("[ERR] Failed to create uart rx thread\n");

    rt_thread_t enc_thread = rt_thread_create("enc_rep", encoder_report_thread,
                                              RT_NULL, 2048, 8, 10);
    if (enc_thread) rt_thread_startup(enc_thread);
    else rt_kprintf("[ERR] Failed to create encoder report thread\n");

    return 0;
}
