/*
 * Copyright (c) 2006-2021, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2026-02-05     lenovo       the first version
 */

#include <rtthread.h>
#include <rtdevice.h>
#include "protocol.h"

/* 声明来自 main.c 的全局标志位与 uart3 发送接口 */
extern volatile rt_bool_t g_send_mpu_data;
extern rt_err_t upper_uart_send(const uint8_t *data, rt_size_t len);

/* MPU6050寄存器定义 */
#define MPU6050_SMPLRT_DIV 0x19
#define MPU6050_CONFIG 0x1A
#define MPU6050_GYRO_CONFIG 0X1B
#define MPU6050_ACCEL_CONFIG 0x1C
#define MPU6050_ACCEL_XOUT_H 0X3B
#define MPU6050_ACCEL_XOUT_L 0x3C
#define MPU6050_ACCEL_YOUT_H 0X3D
#define MPU6050_ACCEL_YOUT_L 0X3E
#define MPU6050_ACCEL_ZOUT_H 0X3F
#define MPU6050_ACCEL_ZOUT_L 0x40
#define MPU6050_TEMP_OUT_H 0x41
#define MPU6050_TEMP_OUT_L 0x42
#define MPU6050_GYRO_XOUT_H 0x43
#define MPU6050_GYRO_XOUT_L 0x44
#define MPU6050_GYRO_YOUT_H 0X45
#define MPU6050_GYRO_YOUT_L 0x46
#define MPU6050_GYRO_ZOUT_H 0x47
#define MPU6050_GYRO_ZOUT_L 0x48
#define MPU6050_PWR_MGMT_1 0x6B
#define MPU6050_PWR_MGMT_2 0x6C
#define MPU6050_WHO_AM_I 0x75

/* MPU6050设备地址（7位地址） */
#define MPU6050_ADDR 0x68

/* 量程配置（严格遵循MPU6050手册4.4/4.5节） */
#define GYRO_RANGE      0x18    // FS_SEL=3 → ±2000dps（bit4=1, bit3=1）
#define ACCEL_RANGE     0x18    // AFS_SEL=3 → ±16g（bit4=1, bit3=1）

/* 转换系数（对应量程的LSB灵敏度） */
#define ACCEL_SENSITIVITY_16G    2048.0f  // LSB/g（±16g量程）
#define GYRO_SENSITIVITY_2000DPS 16.4f   // LSB/(°/s)（±2000dps量程）

/* IMU 帧上报周期(ms) */
#define MPU_REPORT_PERIOD_MS     100

/* 全局变量 */
static struct rt_i2c_bus_device *g_i2c_dev = RT_NULL;
static rt_mutex_t g_i2c_mutex = RT_NULL;  // I2C总线互斥锁

/* 写入寄存器（带互斥锁保护） */
rt_err_t MPU6050_WriteReg(uint8_t RegAddress, uint8_t Data) {
    if (g_i2c_dev == RT_NULL) {
        rt_kprintf("[MPU6050] I2C device not initialized\n");
        return -RT_ERROR;
    }
    if (rt_mutex_take(g_i2c_mutex, RT_WAITING_FOREVER) != RT_EOK) {
        rt_kprintf("[MPU6050] Take I2C mutex failed\n");
        return -RT_ERROR;
    }

    rt_kprintf("[MPU6050] Writing to register 0x%02X with value 0x%02X\n", RegAddress, Data);

    struct rt_i2c_msg msg;
    uint8_t buf[2] = {RegAddress, Data};
    
    msg.addr  = MPU6050_ADDR;
    msg.flags = RT_I2C_WR;
    msg.buf   = buf;
    msg.len   = 2;
    
    rt_err_t result = -RT_ERROR;
    
    /* 添加调试信息，检查I2C总线设备状态 */
    if (g_i2c_dev == NULL) {
        rt_kprintf("[MPU6050] ERROR: g_i2c_dev is NULL\n");
    } else {
        rt_kprintf("[MPU6050] g_i2c_dev address: 0x%08X\n", (uint32_t)g_i2c_dev);

        if (g_i2c_dev->ops == NULL) {
            rt_kprintf("[MPU6050] ERROR: g_i2c_dev->ops is NULL\n");
        } else {
            rt_kprintf("[MPU6050] g_i2c_dev->ops address: 0x%08X\n", (uint32_t)g_i2c_dev->ops);

            if (g_i2c_dev->ops->master_xfer == NULL) {
                rt_kprintf("[MPU6050] ERROR: g_i2c_dev->ops->master_xfer is NULL\n");
            } else {
                rt_kprintf("[MPU6050] g_i2c_dev->ops->master_xfer address: 0x%08X\n", (uint32_t)g_i2c_dev->ops->master_xfer);
            }
        }
    }
    
    /* 尝试进行I2C传输 */
    rt_kprintf("[MPU6050] Calling rt_i2c_transfer...\n");
    if (rt_i2c_transfer(g_i2c_dev, &msg, 1) == 1) {
        result = RT_EOK;
        rt_kprintf("[MPU6050] Successfully wrote 0x%02X to register 0x%02X\n", Data, RegAddress);
    } else {
        rt_kprintf("[MPU6050] Failed to write register 0x%02X\n", RegAddress);
    }

    rt_mutex_release(g_i2c_mutex);
    return result;
}

/* 读取单个寄存器（带互斥锁保护） */
rt_err_t MPU6050_ReadReg(uint8_t RegAddress, uint8_t *Data) {
    if (g_i2c_dev == RT_NULL || Data == RT_NULL) {
        rt_kprintf("[MPU6050] Invalid parameters\n");
        return -RT_ERROR;
    }
    if (rt_mutex_take(g_i2c_mutex, RT_WAITING_FOREVER) != RT_EOK) {
        rt_kprintf("[MPU6050] Take I2C mutex failed\n");
        return -RT_ERROR;
    }

    rt_kprintf("[MPU6050] Reading from register 0x%02X\n", RegAddress);

    struct rt_i2c_msg msgs[2];
    uint8_t reg_buf = RegAddress;
    uint8_t data_buf = 0;
    
    /* 发送寄存器地址 */
    msgs[0].addr  = MPU6050_ADDR;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = &reg_buf;
    msgs[0].len   = 1;
    
    /* 读取数据 */
    msgs[1].addr  = MPU6050_ADDR;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = &data_buf;
    msgs[1].len   = 1;
    
    rt_err_t result = -RT_ERROR;
    if (rt_i2c_transfer(g_i2c_dev, msgs, 2) == 2) {
        *Data = data_buf;
        result = RT_EOK;
        rt_kprintf("[MPU6050] Successfully read 0x%02X from register 0x%02X\n", *Data, RegAddress);

        /* 特别标记WHO_AM_I寄存器的读取结果 */
        if (RegAddress == MPU6050_WHO_AM_I) {
            if (*Data == 0x68) {
                rt_kprintf("[MPU6050] WHO_AM_I check passed: 0x%02X (expected 0x68)\n", *Data);
            } else {
                rt_kprintf("[MPU6050] WHO_AM_I check failed: 0x%02X (expected 0x68)\n", *Data);
            }
        }
    } else {
        rt_kprintf("[MPU6050] Failed to read register 0x%02X\n", RegAddress);
    }

    rt_mutex_release(g_i2c_mutex);
    return result;
}

/* 读取加速度计数据（添加I2C传输校验） */
void MPU6050_ReadAccel(int16_t *ax, int16_t *ay, int16_t *az) {
    if (g_i2c_dev == RT_NULL || ax == RT_NULL || ay == RT_NULL || az == RT_NULL) {
        rt_kprintf("[MPU6050] Invalid parameters\n");
        return;
    }
    if (rt_mutex_take(g_i2c_mutex, RT_WAITING_FOREVER) != RT_EOK) {
        rt_kprintf("[MPU6050] Take I2C mutex failed\n");
        return;
    }

    struct rt_i2c_msg msgs[2];
    uint8_t reg_buf = MPU6050_ACCEL_XOUT_H;
    uint8_t data_buf[6] = {0};
    
    /* 发送寄存器地址 */
    msgs[0].addr  = MPU6050_ADDR;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = &reg_buf;
    msgs[0].len   = 1;
    
    /* 读取6字节数据 */
    msgs[1].addr  = MPU6050_ADDR;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = data_buf;
    msgs[1].len   = 6;
    
    /* 校验I2C传输结果，避免垃圾数据 */
    if (rt_i2c_transfer(g_i2c_dev, msgs, 2) == 2) {
        *ax = ((int16_t)data_buf[0] << 8) | data_buf[1];
        *ay = ((int16_t)data_buf[2] << 8) | data_buf[3];
        *az = ((int16_t)data_buf[4] << 8) | data_buf[5];
    } else {
        *ax = *ay = *az = 0;
        rt_kprintf("[MPU6050] I2C read accel failed\n");
    }

    rt_mutex_release(g_i2c_mutex);
}

/* 读取陀螺仪数据（添加I2C传输校验） */
void MPU6050_ReadGyro(int16_t *gx, int16_t *gy, int16_t *gz) {
    if (g_i2c_dev == RT_NULL || gx == RT_NULL || gy == RT_NULL || gz == RT_NULL) {
        rt_kprintf("[MPU6050] Invalid parameters\n");
        return;
    }
    if (rt_mutex_take(g_i2c_mutex, RT_WAITING_FOREVER) != RT_EOK) {
        rt_kprintf("[MPU6050] Take I2C mutex failed\n");
        return;
    }

    struct rt_i2c_msg msgs[2];
    uint8_t reg_buf = MPU6050_GYRO_XOUT_H;
    uint8_t data_buf[6] = {0};
    
    /* 发送寄存器地址 */
    msgs[0].addr  = MPU6050_ADDR;
    msgs[0].flags = RT_I2C_WR;
    msgs[0].buf   = &reg_buf;
    msgs[0].len   = 1;
    
    /* 读取6字节数据 */
    msgs[1].addr  = MPU6050_ADDR;
    msgs[1].flags = RT_I2C_RD;
    msgs[1].buf   = data_buf;
    msgs[1].len   = 6;
    
    /* 校验I2C传输结果，避免垃圾数据 */
    if (rt_i2c_transfer(g_i2c_dev, msgs, 2) == 2) {
        *gx = ((int16_t)data_buf[0] << 8) | data_buf[1];
        *gy = ((int16_t)data_buf[2] << 8) | data_buf[3];
        *gz = ((int16_t)data_buf[4] << 8) | data_buf[5];
    } else {
        *gx = *gy = *gz = 0;
        rt_kprintf("[MPU6050] I2C read gyro failed\n");
    }

    rt_mutex_release(g_i2c_mutex);
}

/* 转换加速度数据为g */
float MPU6050_ConvertAccel(int16_t raw_accel) {
    return (float)raw_accel / ACCEL_SENSITIVITY_16G;
}

/* 转换陀螺仪数据为°/s */
float MPU6050_ConvertGyro(int16_t raw_gyro) {
    return (float)raw_gyro / GYRO_SENSITIVITY_2000DPS;
}

/* MPU6050初始化（使用正确的I2C总线API） */
rt_err_t MPU6050_Init(const char *i2c_bus_name) {
    rt_kprintf("[MPU6050] Initializing...\n");
    
    /* 初始化互斥锁 */
    if (g_i2c_mutex == RT_NULL) {
        g_i2c_mutex = rt_mutex_create("i2c_mutex", RT_IPC_FLAG_FIFO);
        if (g_i2c_mutex == RT_NULL) {
            rt_kprintf("[MPU6050] Create I2C mutex failed\n");
            return -RT_ERROR;
        }
    }

    /* 查找I2C总线设备 */
    g_i2c_dev = rt_i2c_bus_device_find(i2c_bus_name);
    if (g_i2c_dev == RT_NULL) {
        rt_kprintf("[MPU6050] Failed to find I2C bus: %s\n", i2c_bus_name);
        return -RT_ERROR;
    }
    
    rt_kprintf("[MPU6050] I2C bus device found successfully\n");
    
    /* 设备复位（MPU6050手册4.36节） */
    if (MPU6050_WriteReg(MPU6050_PWR_MGMT_1, 0x80) != RT_EOK) {
        rt_kprintf("[MPU6050] Device reset failed\n");
        return -RT_ERROR;
    }
    rt_thread_mdelay(50);  // 等待复位完成（手册要求≥10ms）

    /* 校验WHO_AM_I（确认设备连接） */
    uint8_t who_am_i;
    if (MPU6050_ReadReg(MPU6050_WHO_AM_I, &who_am_i) != RT_EOK || who_am_i != 0x68) {
        rt_kprintf("[MPU6050] Device not found (WHO_AM_I=0x%02X)\n", who_am_i);
        return -RT_ERROR;
    }
    
    /* 配置MPU6050（严格遵循手册时序） */
    MPU6050_WriteReg(MPU6050_PWR_MGMT_1, 0x01);    // 选用X轴陀螺时钟（稳定性最优）
    rt_thread_mdelay(10);
    MPU6050_WriteReg(MPU6050_PWR_MGMT_2, 0x00);    // 使能3轴加速度+3轴陀螺
    MPU6050_WriteReg(MPU6050_SMPLRT_DIV, 0x09);    // 采样分频器=10 → 采样率=100Hz（1kHz/(1+9)）
    MPU6050_WriteReg(MPU6050_CONFIG, 0x06);        // DLPF_CFG=6 → 低通滤波带宽5Hz（降噪）
    MPU6050_WriteReg(MPU6050_GYRO_CONFIG, GYRO_RANGE);   // 陀螺仪量程±2000dps
    MPU6050_WriteReg(MPU6050_ACCEL_CONFIG, ACCEL_RANGE); // 加速度计量程±16g
    
    rt_kprintf("[MPU6050] Initialization completed\n");
    return RT_EOK;
}

/* 读取所有传感器数据 */
rt_err_t MPU6050_ReadSensors(float *ax, float *ay, float *az, float *gx, float *gy, float *gz) {
    if (ax == RT_NULL || ay == RT_NULL || az == RT_NULL || gx == RT_NULL || gy == RT_NULL || gz == RT_NULL) {
        rt_kprintf("[MPU6050] Invalid parameters\n");
        return -RT_ERROR;
    }
    
    int16_t raw_ax, raw_ay, raw_az;
    int16_t raw_gx, raw_gy, raw_gz;
    
    MPU6050_ReadAccel(&raw_ax, &raw_ay, &raw_az);
    MPU6050_ReadGyro(&raw_gx, &raw_gy, &raw_gz);
    
    *ax = MPU6050_ConvertAccel(raw_ax);
    *ay = MPU6050_ConvertAccel(raw_ay);
    *az = MPU6050_ConvertAccel(raw_az);
    *gx = MPU6050_ConvertGyro(raw_gx);
    *gy = MPU6050_ConvertGyro(raw_gy);
    *gz = MPU6050_ConvertGyro(raw_gz);
    
    return RT_EOK;
}

/* IMU 数据上报线程 */
static void mpu6050_test_thread(void *parameter)
{
    float ax, ay, az;
    float gx, gy, gz;
    rt_err_t result;

    rt_thread_mdelay(1000);  // 延迟启动，确保系统初始化完成

    /* 初始化MPU6050 */
    result = MPU6050_Init("i2c1");
    if (result != RT_EOK)
    {
        rt_kprintf("[MPU6050] Test failed: initialization error, code=%d\n", result);
        return;
    }

    rt_kprintf("[MPU6050] Test thread started, reporting IMU frame every %dms\n", MPU_REPORT_PERIOD_MS);

    /* 循环读取数据 */
    while (1)
    {
        if (g_i2c_dev != RT_NULL)
        {
            if (MPU6050_ReadSensors(&ax, &ay, &az, &gx, &gy, &gz) == RT_EOK)
            {
                /* 物理量放大1000倍转整数: 加速度单位 mg, 陀螺单位 m°/s */
                rt_int32_t imu[6];
                imu[0] = (rt_int32_t)(ax * 1000.0f);
                imu[1] = (rt_int32_t)(ay * 1000.0f);
                imu[2] = (rt_int32_t)(az * 1000.0f);
                imu[3] = (rt_int32_t)(gx * 1000.0f);
                imu[4] = (rt_int32_t)(gy * 1000.0f);
                imu[5] = (rt_int32_t)(gz * 1000.0f);

                /* 组 IMU 二进制帧走 uart3, 与编码器帧同一协议 */
                if (g_send_mpu_data)
                {
                    uint8_t frame[PROTO_IMU_FRAME_LEN];
                    rt_size_t n = proto_build_imu(frame, imu);
                    upper_uart_send(frame, n);
                }
            }
        }
        else
        {
            result = MPU6050_Init("i2c1");
            if (result != RT_EOK)
            {
                // rt_kprintf("[MPU6050] Re-initialization failed, code=%d\n", result);
            }
        }

        rt_thread_mdelay(MPU_REPORT_PERIOD_MS);
    }
}

/* 自动初始化函数 */
int mpu6050_auto_init(void) {
    rt_thread_t thread;
    
    /* 创建测试线程（栈大小4096字节，优先级25） */
    thread = rt_thread_create("mpu6050",
                             mpu6050_test_thread,
                             RT_NULL,
                             4096,
                             25,
                             10);
    
    if (thread != RT_NULL) {
        rt_thread_startup(thread);
        return RT_EOK;
    }
    
    return -RT_ERROR;
}

/* 导出为RT-Thread自动初始化函数 */
INIT_APP_EXPORT(mpu6050_auto_init);
