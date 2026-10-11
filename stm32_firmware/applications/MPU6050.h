#ifndef __MPU6050_REG_H
#define __MPU6050_REG_H

#include <rtthread.h>

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

/* 函数原型声明 */
rt_err_t MPU6050_WriteReg(uint8_t RegAddress, uint8_t Data);
rt_err_t MPU6050_ReadReg(uint8_t RegAddress, uint8_t *Data);
void MPU6050_SetPowerMode(uint8_t mode);
void MPU6050_SetSampleRate(uint8_t div);
void MPU6050_EnableSensors(void);
void MPU6050_ReadAccel(int16_t *ax, int16_t *ay, int16_t *az);
void MPU6050_ReadGyro(int16_t *gx, int16_t *gy, int16_t *gz);
float MPU6050_ConvertAccel(int16_t raw_accel, uint8_t range);
float MPU6050_ConvertGyro(int16_t raw_gyro, uint8_t range);
rt_err_t MPU6050_Init(const char *i2c_bus_name);
void MPU6050_ReadSensors(float *ax, float *ay, float *az, float *gx, float *gy, float *gz);
int mpu6050_auto_init(void);

#endif
